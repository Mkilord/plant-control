"""Реестр машин: живые доменные объекты в памяти плюс запись в SQLite.

Почему в памяти: полив длится секунды и минуты, и все запросы в это время должны
видеть один и тот же объект машины. Иначе второй запрос загрузил бы из базы
свежую копию, не знающую о текущем поливе, и правило "один полив за раз"
не сработало бы.

Реестр реализует порт MachineRepository из ядра.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from plant_control.domain.collector import ValveState
from plant_control.domain.errors import MachineBusyError, UnknownRouteError
from plant_control.domain.machine import WateringMachine

from plant_control_addon.config import (
    MachineConfig,
    MachineState,
    build_machine,
    state_of,
)
from plant_control_addon.storage import MachineStore

log = logging.getLogger(__name__)


class UnknownMachineError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WateringResult:
    route_id: str
    dose_ml: float
    started_at: datetime
    finished_at: datetime
    ok: bool
    error: str | None = None


@dataclass
class MachineEntry:
    id: str
    config: MachineConfig
    machine: WateringMachine
    task: asyncio.Task[None] | None = None
    last_watering: WateringResult | None = None

    @property
    def is_busy(self) -> bool:
        return self.machine.is_busy or (self.task is not None and not self.task.done())


class MachineRegistry:
    def __init__(self, store: MachineStore) -> None:
        self._store = store
        self._entries: dict[str, MachineEntry] = {}

    async def load(self) -> None:
        await self._store.open()
        for row in await self._store.load_all():
            try:
                config = MachineConfig.model_validate_json(row.config_json)
                state = MachineState.model_validate_json(row.state_json)
                machine = build_machine(row.id, config, state)
            except Exception:
                # Сломанная запись не должна мешать остальным машинам.
                log.exception("cannot load machine %s, skipped", row.id)
                continue
            self._entries[row.id] = MachineEntry(row.id, config, machine)

    # --- Порт MachineRepository ---

    async def get(self, machine_id: str) -> WateringMachine:
        return self.entry(machine_id).machine

    async def save(self, machine: WateringMachine) -> None:
        await self._store.save_state(machine.id, state_of(machine))

    # --- Доступ ---

    def entries(self) -> list[MachineEntry]:
        return list(self._entries.values())

    def machines(self) -> list[WateringMachine]:
        """Порт MachineDirectory для проверки состояния."""
        return [entry.machine for entry in self._entries.values()]

    def entry(self, machine_id: str) -> MachineEntry:
        try:
            return self._entries[machine_id]
        except KeyError:
            raise UnknownMachineError(f"unknown machine {machine_id!r}") from None

    # --- CRUD конфигурации ---

    async def create(self, config: MachineConfig) -> MachineEntry:
        machine_id = f"m-{uuid.uuid4().hex[:8]}"
        machine = build_machine(machine_id, config, MachineState())
        await self._store.upsert(machine_id, config, state_of(machine))
        entry = MachineEntry(machine_id, config, machine)
        self._entries[machine_id] = entry
        return entry

    async def update(self, machine_id: str, config: MachineConfig) -> MachineEntry:
        """Новая конфигурация, состояние сохраняется там, где это имеет смысл."""
        old = self.entry(machine_id)
        if old.is_busy:
            raise MachineBusyError(f"machine {machine_id!r} is watering")
        state = state_of(old.machine)
        # Клапаны, которых раньше не было, могли остаться открытыми в железе:
        # считаем их неизвестными, безопасный старт после обновления закроет их.
        known = state.valve_states
        state.valve_states = {
            route.id: known.get(route.id, ValveState.UNKNOWN.value) for route in config.routes
        }
        if type(config.plumbing) is not type(old.config.plumbing):
            state.supply_is_filled = False
        machine = build_machine(machine_id, config, state)
        await self._store.upsert(machine_id, config, state_of(machine))
        entry = MachineEntry(machine_id, config, machine, last_watering=old.last_watering)
        self._entries[machine_id] = entry
        return entry

    async def set_route_dose(self, machine_id: str, route_id: str, dose_ml: float) -> None:
        """Доза по умолчанию для растения. Машину не пересобираем: расчёт от неё не зависит."""
        entry = self.entry(machine_id)
        config = entry.config.model_copy(deep=True)
        for route in config.routes:
            if route.id == route_id:
                route.default_dose_ml = dose_ml
                break
        else:
            raise UnknownRouteError(f"unknown route {route_id!r}")
        entry.config = config
        await self._store.upsert(machine_id, config, state_of(entry.machine))

    async def delete(self, machine_id: str) -> None:
        entry = self.entry(machine_id)
        if entry.is_busy:
            raise MachineBusyError(f"machine {machine_id!r} is watering")
        await self._store.delete(machine_id)
        del self._entries[machine_id]
