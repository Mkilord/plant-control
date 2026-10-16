"""Управление машинами: действия API и фоновые задачи.

Связывает сервисы ядра (WateringService, SafetyService) с реестром и Home Assistant.
Порты насоса и клапанов создаются на каждую машину: они переводят id устройства
внутри машины ("pump", id маршрута) в сущность HA по её конфигурации.
"""

import asyncio
import contextlib
import logging
from collections.abc import Coroutine, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from plant_control.application.actuation import Actuation
from plant_control.application.health import HealthReport, HealthService
from plant_control.application.notifications import Event, NotificationService
from plant_control.application.ports import Clock, Sleeper
from plant_control.application.queue import (
    RequestSource,
    WateringQueue,
    WateringRequest,
)
from plant_control.application.safety_service import SafetyService
from plant_control.application.watering_service import WateringService, WateringTimings
from plant_control.domain.errors import MachineBusyError, WateringBlockedError
from plant_control.domain.problems import Observation, Problem, ProblemKind
from plant_control.domain.pump import PumpState
from plant_control.domain.watering import WateringPlan

from plant_control_addon.config import FlowSuggestionState
from plant_control_addon.ha.client import EntityState
from plant_control_addon.ha.devices import HaPumpControl, HaValveControl, ServiceCaller
from plant_control_addon.health_source import HaHealthSource
from plant_control_addon.registry import MachineEntry, MachineRegistry, WateringResult

if TYPE_CHECKING:
    from plant_control_addon.calibration import CalibrationManager

log = logging.getLogger(__name__)

CALIBRATION_IGNORES = frozenset({ProblemKind.CALIBRATION_STALE})

# Насос включился сам: сколько ждать подтверждения выключения перед повтором команды,
# сколько повторов до признания состояния неизвестным и сколько держать проблему.
UNEXPECTED_RETRY = timedelta(seconds=3)
# Сразу после полива HA может ещё показывать "on": даём реле время отчитаться.
UNEXPECTED_GRACE = timedelta(seconds=5)
UNEXPECTED_ATTEMPTS = 3
UNEXPECTED_PROBLEM_FOR = timedelta(minutes=30)


@dataclass
class PumpWatch:
    """Что HA говорит о реле насоса и что сторож уже сделал."""

    on: bool
    since: datetime
    attempts: int = 0
    last_attempt: datetime | None = None


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class AsyncioSleeper:
    async def sleep(self, duration: timedelta) -> None:
        await asyncio.sleep(duration.total_seconds())


class Journal(Protocol):
    """Куда сохранять завершённые поливы. Обычно база add-on'а."""

    async def save_watering(self, request: WateringRequest) -> None: ...


class Controller:
    def __init__(
        self,
        registry: MachineRegistry,
        ha: ServiceCaller,
        *,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
        health: HealthService | None = None,
        health_source: HaHealthSource | None = None,
        notifications: NotificationService | None = None,
        queue_tick: float = 0.1,
        journal: Journal | None = None,
        history: Iterable[WateringRequest] = (),
    ) -> None:
        self._registry = registry
        self._journal = journal
        self._health = health
        self._notifications = notifications
        self._health_source = health_source
        self._ha = ha
        self._clock: Clock = clock or SystemClock()
        self._sleeper: Sleeper = sleeper or AsyncioSleeper()
        self._background: set[asyncio.Task[Any]] = set()
        # Мастер калибровки. Подключается после создания: ему самому нужен контроллер.
        self.calibration: CalibrationManager | None = None
        # Фактическое состояние реле насосов по HA: сторож сверяет его с ожидаемым.
        self._pump_watch: dict[str, PumpWatch] = {}
        # Реле, которые сейчас включают нарочно (проверка из мастера): до какого времени.
        self._settle_until: dict[str, datetime] = {}
        self._allowed_on: dict[str, datetime] = {}
        # Машины, у которых насос включался без команды: когда и что.
        self._unexpected: dict[str, tuple[datetime, str]] = {}
        # Очередь поливов: она же следит за группами питания.
        # Сам контроллер для неё - исполнитель (метод water).
        self.queue = WateringQueue(
            self,
            self._clock,
            registry.power_group,
            tick=queue_tick,
            history=history,
            on_finished=self._save_to_journal,
        )

    def now(self) -> datetime:
        return self._clock.now()

    async def sleep_s(self, seconds: float) -> None:
        await self._sleeper.sleep(timedelta(seconds=seconds))

    @property
    def registry(self) -> MachineRegistry:
        return self._registry

    # --- Сервисы ядра для конкретной машины ---

    def _ports(self, entry: MachineEntry) -> tuple[HaPumpControl, HaValveControl]:
        resolve = entry.setup.entity_for
        return HaPumpControl(self._ha, resolve), HaValveControl(self._ha, resolve)

    def _watering(self, entry: MachineEntry) -> WateringService:
        pumps, valves = self._ports(entry)
        timings = WateringTimings(
            valve_lead=timedelta(seconds=entry.setup.timings.valve_lead_s),
            valve_lag=timedelta(seconds=entry.setup.timings.valve_lag_s),
        )
        return WateringService(self._registry, pumps, valves, self._clock, self._sleeper, timings)

    def actuation(self, entry: MachineEntry) -> Actuation:
        pumps, valves = self._ports(entry)
        return Actuation(pumps, valves, self._clock)

    def _safety(self, entry: MachineEntry) -> SafetyService:
        pumps, valves = self._ports(entry)
        return SafetyService(self._registry, pumps, valves, self._clock)

    # --- Действия ---

    async def plan(self, machine_id: str, route_id: str, dose_ml: float) -> WateringPlan:
        entry = self._registry.entry(machine_id)
        return await self._watering(entry).plan(machine_id, route_id, dose_ml)

    async def start_watering(
        self,
        machine_id: str,
        route_id: str,
        dose_ml: float,
        source: RequestSource = RequestSource.MANUAL,
    ) -> tuple[WateringPlan, WateringRequest]:
        """Проверить правила и поставить полив в очередь. Возвращает план и заявку."""
        entry = self._registry.entry(machine_id)
        if self.is_busy(machine_id):
            raise MachineBusyError(f"machine {machine_id!r} is watering")
        await self.ensure_can_water(machine_id, route_id)
        # План считаем сразу: так неверная доза или пустой бак видны в ответе.
        plan = await self._watering(entry).plan(machine_id, route_id, dose_ml)
        request = self.queue.submit(machine_id, route_id, dose_ml, source=source)
        return plan, request

    def blockers(
        self,
        machine_id: str,
        route_id: str | None = None,
        ignore: frozenset[ProblemKind] = frozenset(),
    ) -> list[Problem]:
        """Открытые проблемы, из-за которых поливать нельзя. route_id - только для растения."""
        if self._health is None:
            return []
        targets: set[str] | None = None
        if route_id is not None:
            targets = {route_id}
            valve_id = self._registry.entry(machine_id).machine.valve_for(route_id)
            if valve_id is not None:
                targets.add(valve_id)
        problems = self._health.board.blocking_for(machine_id, self._clock.now(), targets)
        return [problem for problem in problems if problem.kind not in ignore]

    async def ensure_can_water(
        self,
        machine_id: str,
        route_id: str,
        ignore: frozenset[ProblemKind] = frozenset(),
    ) -> None:
        """Проверить состояние прямо сейчас и отказать, если полив невозможен.

        Проверка свежая, а не из последнего круга: насос мог пропасть секунду назад.
        """
        self._registry.entry(machine_id)
        if self._health is None:
            return
        await self.check_health()
        problems = self.blockers(machine_id, route_id, ignore)
        if problems:
            kinds = ", ".join(problem.kind.value for problem in problems)
            raise WateringBlockedError(f"watering is blocked: {kinds}", problems)

    async def ensure_can_calibrate(self, machine_id: str, route_id: str) -> None:
        """Как для полива, только устаревшая калибровка не мешает: её и меняют."""
        await self.ensure_can_water(machine_id, route_id, CALIBRATION_IGNORES)

    def is_busy(self, machine_id: str) -> bool:
        """Занята, если поливает, ждёт своей очереди или калибруется."""
        return self.is_watering(machine_id) or self.is_calibrating(machine_id)

    def is_calibrating(self, machine_id: str) -> bool:
        return self.calibration is not None and self.calibration.active_for(machine_id) is not None

    def is_watering(self, machine_id: str) -> bool:
        entry = self._registry.entry(machine_id)
        if entry.is_busy:
            return True
        return any(not r.is_finished for r in self.queue.for_machine(machine_id))

    async def water(self, machine_id: str, route_id: str, dose_ml: float) -> None:
        """Исполнитель для очереди: полив от начала до конца."""
        await self._run_watering(self._registry.entry(machine_id), route_id, dose_ml)

    async def _run_watering(self, entry: MachineEntry, route_id: str, dose_ml: float) -> None:
        started = self._clock.now()
        try:
            await self._run_watering_steps(entry, route_id, dose_ml, started)
        finally:
            self._settle_until[entry.id] = self._clock.now() + UNEXPECTED_GRACE

    async def _run_watering_steps(
        self, entry: MachineEntry, route_id: str, dose_ml: float, started: datetime
    ) -> None:
        failure: Exception | None = None
        try:
            # Пока заявка ждала очереди, могло что-то сломаться: проверяем перед самым стартом.
            if self.is_calibrating(entry.id):
                raise MachineBusyError(f"machine {entry.id!r} is being calibrated")
            await self.ensure_can_water(entry.id, route_id)
            await self._watering(entry).water(entry.id, route_id, dose_ml)
        except asyncio.CancelledError:
            # Отмена: результат записываем, уведомление не отправляем -
            # в отменённой задаче любое ожидание сразу прерывается.
            self._record(entry, route_id, dose_ml, started, "cancelled")
            raise
        except WateringBlockedError as exc:
            log.warning("watering %s/%s blocked: %s", entry.id, route_id, exc)
            failure = exc
        except Exception as exc:
            log.exception("watering %s/%s failed", entry.id, route_id)
            failure = exc
        if failure is None:
            self._record(entry, route_id, dose_ml, started, None)
        else:
            self._record(entry, route_id, dose_ml, started, f"{type(failure).__name__}: {failure}")
        await self._notify_watering(entry, route_id, dose_ml)
        if failure is not None:
            # Очередь должна увидеть неудачу: заявка станет failed, а не done.
            raise failure

    def _record(
        self,
        entry: MachineEntry,
        route_id: str,
        dose_ml: float,
        started: datetime,
        error: str | None,
    ) -> None:
        entry.last_watering = WateringResult(
            route_id=route_id,
            dose_ml=dose_ml,
            started_at=started,
            finished_at=self._clock.now(),
            ok=error is None,
            error=error,
        )
        if error is None:
            # Расписание смотрит на это время: недавно политое растение пропускается.
            entry.watered_at[route_id] = started

    async def _notify_watering(self, entry: MachineEntry, route_id: str, dose_ml: float) -> None:
        if self._notifications is None:
            return
        result = entry.last_watering
        name = entry.config.name
        plant = self._plant_name(entry, route_id)
        if result is not None and not result.ok:
            event = self._notifications.watering_failed(
                entry.id, name, plant, dose_ml, result.error or ""
            )
        else:
            event = self._notifications.watering_done(entry.id, name, plant, dose_ml)
        await self._notifications.emit(event)

    def names(self, machine_id: str, route_id: str) -> tuple[str | None, str]:
        """Название машины и растения для показа. None - машины уже нет."""
        try:
            entry = self._registry.entry(machine_id)
        except Exception:
            return None, route_id
        return entry.config.name, self._plant_name(entry, route_id)

    def _plant_name(self, entry: MachineEntry, route_id: str) -> str:
        for route in entry.config.routes:
            if route.id == route_id:
                return route.name or route.id
        return route_id

    async def emergency_stop(self, machine_id: str) -> list[Exception]:
        entry = self._registry.entry(machine_id)
        if self.calibration is not None:
            await self.calibration.abort_machine(machine_id)
        await self._cancel_queue(machine_id)
        await self._cancel_watering(entry)
        errors = await self._safety(entry).emergency_stop(machine_id)
        # Стоп мог снять "состояние насоса неизвестно": обновить проблемы сразу.
        await self.recheck()
        return errors

    async def safe_start(self, machine_id: str) -> list[Exception]:
        entry = self._registry.entry(machine_id)
        errors = await self._safety(entry).safe_start(machine_id)
        for error in errors:
            log.warning("safe start %s: %s", machine_id, error)
        return errors

    async def safe_start_all(self) -> None:
        for entry in self._registry.entries():
            if not self.is_busy(entry.id):
                await self.safe_start(entry.id)

    async def refill(self, machine_id: str, volume_ml: float | None) -> None:
        """Долить воду. None - долить до полного."""
        entry = self._registry.entry(machine_id)
        if volume_ml is None:
            entry.machine.fill_tank_full()
        else:
            entry.machine.tank.fill(volume_ml)
        await self._registry.save(entry.machine)
        await self.recheck()

    async def set_tank_volume(self, machine_id: str, volume_ml: float) -> None:
        entry = self._registry.entry(machine_id)
        if entry.is_busy:
            raise MachineBusyError(f"machine {machine_id!r} is watering")
        thresholds = self.calibration.settings.tuning() if self.calibration else None
        suggestion = entry.machine.measure_tank(volume_ml, self._clock.now(), thresholds)
        if suggestion is not None:
            log.info("flow of %s looks off by x%.2f", machine_id, suggestion.factor)
            entry.flow_suggestion = FlowSuggestionState.of(suggestion)
        await self._registry.save(entry.machine)
        await self.recheck()

    async def shutdown(self) -> None:
        if self.calibration is not None:
            await self.calibration.shutdown()
        for task in list(self._background):
            task.cancel()
        for entry in self._registry.entries():
            if entry.machine.is_busy or entry.id in self._queue_machines():
                await self.emergency_stop(entry.id)
        # Прерванные поливы только что попали в журнал: дать записям дойти до базы.
        pending = [task for task in self._background if not task.done()]
        if pending:
            await asyncio.wait(pending, timeout=2)

    def _queue_machines(self) -> set[str]:
        return {request.machine_id for request in self.queue.running()}

    async def _cancel_queue(self, machine_id: str) -> None:
        """Снять заявки машины и дождаться, пока прервётся текущий полив."""
        cancelled = self.queue.cancel_machine(machine_id)
        if cancelled:
            # Отмена задачи доходит до полива не мгновенно.
            for _ in range(200):
                if not self._registry.entry(machine_id).machine.is_busy:
                    break
                await asyncio.sleep(0.005)

    # --- Проверка состояния ---

    async def check_health(self) -> HealthReport | None:
        """Снять срез состояния и обновить доску проблем."""
        if self._health is None:
            return None
        extra = await self._health_source.observations() if self._health_source else []
        extra = [*extra, *self._unexpected_observations()]
        if self._health_source is not None:
            self._learn_states(self._health_source.last_states)
        report = self._health.check(extra)
        for problem in report.opened:
            log.warning(
                "problem opened: %s %s %s", problem.machine_id, problem.kind, problem.details
            )
        for problem in report.closed:
            log.info("problem closed: %s %s", problem.machine_id, problem.kind)
        # Пуши уходят в фоне: проверка стоит перед каждым поливом и прогоном калибровки,
        # и ждать ответа телефона там незачем.
        if report.opened or report.closed:
            self._spawn(self._notify_problems_safely(report))
        return report

    async def recheck(self) -> None:
        """Проверка после действия человека: не должна ломать само действие."""
        try:
            await self.check_health()
        except Exception:
            log.exception("health check failed")

    async def _notify_problems_safely(self, report: HealthReport) -> None:
        try:
            await self._notify_problems(report)
        except Exception:
            log.exception("cannot send problem notifications")

    async def _notify_problems(self, report: HealthReport) -> None:
        if self._notifications is None:
            return
        events: list[Event] = []
        for problem in report.opened:
            name = self._machine_name(problem.machine_id)
            events.append(self._notifications.problem_opened(problem.machine_id, name, problem))
        for problem in report.closed:
            name = self._machine_name(problem.machine_id)
            events.append(self._notifications.problem_closed(problem.machine_id, name, problem))
        await self._notifications.emit_all(events)

    def _machine_name(self, machine_id: str) -> str:
        try:
            return self._registry.entry(machine_id).config.name
        except Exception:
            return machine_id

    async def health_loop(self, interval: float = 30.0) -> None:
        while True:
            try:
                await self.check_health()
            except Exception:
                log.exception("health check failed")
            await asyncio.sleep(interval)

    # --- Журнал ---

    def _save_to_journal(self, request: WateringRequest) -> None:
        if self._journal is not None:
            self._spawn(self._write_journal(self._journal, request))

    async def _write_journal(self, journal: Journal, request: WateringRequest) -> None:
        try:
            await journal.save_watering(request)
        except Exception:
            log.exception("cannot save watering %s to the journal", request.id)

    # --- Фоновые задачи ---

    async def watchdog(self, interval: float = 1.0) -> None:
        """Сторож: раз в interval проверяет насосы.

        - насос работает дольше предела - аварийная остановка;
        - HA показывает насос включённым, а машина не поливает и не калибруется -
          выключить и повторять, пока реле не подтвердит выключение.
        """
        while True:
            for entry in self._registry.entries():
                try:
                    await self._check_stray_pump(entry)
                    if entry.machine.pump.state is not PumpState.ON:
                        continue
                    if await self._safety(entry).check_overrun(entry.id):
                        log.error("pump of %s ran over its limit, stopped", entry.id)
                        await self._cancel_watering(entry)
                except Exception:
                    log.exception("watchdog failed for %s", entry.id)
            await asyncio.sleep(interval)

    # --- Насос, включившийся без команды ---

    def allow_pump_on(self, entity_id: str, seconds: float) -> None:
        """Реле включают нарочно (проверка из мастера): не считать это сбоем."""
        self._allowed_on[entity_id] = self._clock.now() + timedelta(seconds=seconds)

    def _expects_pump_on(self, entry: MachineEntry) -> bool:
        now = self._clock.now()
        if entry.is_busy or self.is_calibrating(entry.id):
            # Полив или калибровка идёт: и ещё немного после конца.
            self._settle_until[entry.id] = now + UNEXPECTED_GRACE
            return True
        settle = self._settle_until.get(entry.id)
        if settle is not None and now < settle:
            return True
        allowed = self._allowed_on.get(entry.config.pump.entity_id)
        return allowed is not None and now < allowed

    def _learn_states(self, states: dict[str, str]) -> None:
        """Состояния из полной выборки HA: только для реле, о которых ещё нет событий."""
        for entry in self._registry.entries():
            entity = entry.config.pump.entity_id
            state = states.get(entity)
            if entity not in self._pump_watch and state in ("on", "off"):
                self._pump_watch[entity] = PumpWatch(on=state == "on", since=self._clock.now())

    async def _check_stray_pump(self, entry: MachineEntry) -> None:
        """HA показывает насос включённым, хотя машина ничего не делает: выключить."""
        watch = self._pump_watch.get(entry.config.pump.entity_id)
        if watch is None or not watch.on or self._expects_pump_on(entry):
            if watch is not None and not watch.on:
                watch.attempts = 0
            return
        now = self._clock.now()
        if watch.last_attempt is not None and now - watch.last_attempt < UNEXPECTED_RETRY:
            return
        if watch.attempts >= UNEXPECTED_ATTEMPTS:
            # Реле не выключается: дальше пусть решает человек, полив запрещён.
            if entry.machine.pump.state is not PumpState.UNKNOWN:
                log.error(
                    "pump %s of %s stays on after %d off commands",
                    entry.config.pump.entity_id,
                    entry.id,
                    watch.attempts,
                )
                entry.machine.pump.mark_unknown()
                await self._registry.save(entry.machine)
                await self.recheck()
            return
        watch.attempts += 1
        watch.last_attempt = now
        await self._stop_stray_pump(entry, watch.attempts)

    async def _stop_stray_pump(self, entry: MachineEntry, attempt: int) -> None:
        entity = entry.config.pump.entity_id
        log.warning(
            "pump %s of %s is on but nothing is running, turning it off (attempt %d)",
            entity,
            entry.id,
            attempt,
        )
        first = entry.id not in self._unexpected
        self._unexpected[entry.id] = (self._clock.now(), entity)
        errors = await self._safety(entry).safe_start(entry.id)
        for error in errors:
            log.error("cannot stop stray pump of %s: %s", entry.id, error)
        if first:
            await self.recheck()

    def _unexpected_observations(self) -> list[Observation]:
        now = self._clock.now()
        found: list[Observation] = []
        for machine_id, (at, entity) in list(self._unexpected.items()):
            if now - at > UNEXPECTED_PROBLEM_FOR:
                del self._unexpected[machine_id]
                continue
            found.append(
                Observation(
                    machine_id,
                    ProblemKind.PUMP_UNEXPECTED_ON,
                    target=entity,
                    details=(
                        f"Реле {entity} включилось, когда машина не поливала. Add-on его выключил"
                    ),
                )
            )
        return found

    def on_connected(self) -> None:
        """HA (пере)подключился: привести железо в безопасное состояние."""
        self._spawn(self.safe_start_all())

    def on_state_changed(self, entity_id: str, state: EntityState | None) -> None:
        """HA сообщил новое состояние сущности: синхронизировать насосы.

        Насос включился, а машина не поливает и не калибруется: это не ручное
        включение, а сбой (потерянная команда выключения, запоздалое состояние
        многоканального модуля). Такой насос сразу выключается.
        """
        if state is None or state.state not in ("on", "off"):
            return
        is_on = state.state == "on"
        for entry in self._registry.entries():
            if entry.config.pump.entity_id != entity_id:
                continue
            watch = self._pump_watch.get(entity_id)
            if watch is None or watch.on != is_on:
                self._pump_watch[entity_id] = PumpWatch(on=is_on, since=self._clock.now())
            safety = self._safety(entry)
            self._spawn(safety.observe_pump_state(entry.id, is_on=is_on))
            if is_on and not self._expects_pump_on(entry):
                self._spawn(self._check_stray_pump(entry))

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
