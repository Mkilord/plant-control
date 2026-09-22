"""Управление машинами: действия API и фоновые задачи.

Связывает сервисы ядра (WateringService, SafetyService) с реестром и Home Assistant.
Порты насоса и клапанов создаются на каждую машину: они переводят id устройства
внутри машины ("pump", id маршрута) в сущность HA по её конфигурации.
"""

import asyncio
import contextlib
import logging
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from plant_control.application.ports import Clock, Sleeper
from plant_control.application.safety_service import SafetyService
from plant_control.application.watering_service import WateringService, WateringTimings
from plant_control.domain.errors import MachineBusyError
from plant_control.domain.pump import PumpState
from plant_control.domain.watering import WateringPlan

from plant_control_addon.ha.client import EntityState
from plant_control_addon.ha.devices import HaPumpControl, HaValveControl, ServiceCaller
from plant_control_addon.registry import MachineEntry, MachineRegistry, WateringResult

log = logging.getLogger(__name__)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class AsyncioSleeper:
    async def sleep(self, duration: timedelta) -> None:
        await asyncio.sleep(duration.total_seconds())


class Controller:
    def __init__(
        self,
        registry: MachineRegistry,
        ha: ServiceCaller,
        *,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._registry = registry
        self._ha = ha
        self._clock: Clock = clock or SystemClock()
        self._sleeper: Sleeper = sleeper or AsyncioSleeper()
        self._background: set[asyncio.Task[Any]] = set()

    # --- Сервисы ядра для конкретной машины ---

    def _ports(self, entry: MachineEntry) -> tuple[HaPumpControl, HaValveControl]:
        resolve = entry.config.entity_for
        return HaPumpControl(self._ha, resolve), HaValveControl(self._ha, resolve)

    def _watering(self, entry: MachineEntry) -> WateringService:
        pumps, valves = self._ports(entry)
        timings = WateringTimings(
            valve_lead=timedelta(seconds=entry.config.timings.valve_lead_s),
            valve_lag=timedelta(seconds=entry.config.timings.valve_lag_s),
        )
        return WateringService(self._registry, pumps, valves, self._clock, self._sleeper, timings)

    def _safety(self, entry: MachineEntry) -> SafetyService:
        pumps, valves = self._ports(entry)
        return SafetyService(self._registry, pumps, valves, self._clock)

    # --- Действия ---

    async def plan(self, machine_id: str, route_id: str, dose_ml: float) -> WateringPlan:
        entry = self._registry.entry(machine_id)
        return await self._watering(entry).plan(machine_id, route_id, dose_ml)

    async def start_watering(self, machine_id: str, route_id: str, dose_ml: float) -> WateringPlan:
        """Проверить правила и запустить полив в фоне. Возвращает план."""
        entry = self._registry.entry(machine_id)
        if entry.is_busy:
            raise MachineBusyError(f"machine {machine_id!r} is watering")
        plan = await self._watering(entry).plan(machine_id, route_id, dose_ml)
        entry.task = asyncio.create_task(
            self._run_watering(entry, route_id, dose_ml), name=f"watering-{machine_id}"
        )
        return plan

    async def _run_watering(self, entry: MachineEntry, route_id: str, dose_ml: float) -> None:
        started = self._clock.now()
        error: str | None = None
        try:
            await self._watering(entry).water(entry.id, route_id, dose_ml)
        except asyncio.CancelledError:
            error = "cancelled"
            raise
        except Exception as exc:
            log.exception("watering %s/%s failed", entry.id, route_id)
            error = f"{type(exc).__name__}: {exc}"
        finally:
            entry.last_watering = WateringResult(
                route_id=route_id,
                dose_ml=dose_ml,
                started_at=started,
                finished_at=self._clock.now(),
                ok=error is None,
                error=error,
            )

    async def emergency_stop(self, machine_id: str) -> list[Exception]:
        entry = self._registry.entry(machine_id)
        await self._cancel_watering(entry)
        return await self._safety(entry).emergency_stop(machine_id)

    async def safe_start(self, machine_id: str) -> list[Exception]:
        entry = self._registry.entry(machine_id)
        errors = await self._safety(entry).safe_start(machine_id)
        for error in errors:
            log.warning("safe start %s: %s", machine_id, error)
        return errors

    async def safe_start_all(self) -> None:
        for entry in self._registry.entries():
            if not entry.is_busy:
                await self.safe_start(entry.id)

    async def refill(self, machine_id: str, volume_ml: float | None) -> None:
        """Долить воду. None - долить до полного."""
        entry = self._registry.entry(machine_id)
        if volume_ml is None:
            entry.machine.tank.fill_full()
        else:
            entry.machine.tank.fill(volume_ml)
        await self._registry.save(entry.machine)

    async def set_tank_volume(self, machine_id: str, volume_ml: float) -> None:
        entry = self._registry.entry(machine_id)
        if entry.is_busy:
            raise MachineBusyError(f"machine {machine_id!r} is watering")
        entry.machine.tank.set_measured_volume(volume_ml)
        await self._registry.save(entry.machine)

    async def shutdown(self) -> None:
        for task in list(self._background):
            task.cancel()
        for entry in self._registry.entries():
            if entry.task is not None and not entry.task.done():
                await self.emergency_stop(entry.id)

    # --- Фоновые задачи ---

    async def watchdog(self, interval: float = 1.0) -> None:
        """Сторож: раз в interval проверяет, не работает ли насос дольше предела."""
        while True:
            for entry in self._registry.entries():
                if entry.machine.pump.state is not PumpState.ON:
                    continue
                try:
                    if await self._safety(entry).check_overrun(entry.id):
                        log.error("pump of %s ran over its limit, stopped", entry.id)
                        await self._cancel_watering(entry)
                except Exception:
                    log.exception("watchdog failed for %s", entry.id)
            await asyncio.sleep(interval)

    def on_connected(self) -> None:
        """HA (пере)подключился: привести железо в безопасное состояние."""
        self._spawn(self.safe_start_all())

    def on_state_changed(self, entity_id: str, state: EntityState | None) -> None:
        """HA сообщил новое состояние сущности: синхронизировать насосы."""
        if state is None or state.state not in ("on", "off"):
            return
        for entry in self._registry.entries():
            if entry.config.pump.entity_id == entity_id:
                safety = self._safety(entry)
                self._spawn(safety.observe_pump_state(entry.id, is_on=state.state == "on"))

    # --- Внутреннее ---

    async def _cancel_watering(self, entry: MachineEntry) -> None:
        task = entry.task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        # Держим ссылку на задачу, иначе сборщик мусора может удалить её до завершения.
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
