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
from dataclasses import dataclass, field
from datetime import datetime

from plant_control.domain.collector import ValveState
from plant_control.domain.errors import MachineBusyError, UnknownRouteError
from plant_control.domain.machine import WateringMachine
from plant_control.domain.power import PowerGroup
from plant_control.domain.schedule import Schedule

from plant_control_addon.config import (
    FlowPointConfig,
    FlowSuggestionState,
    MachineConfig,
    MachineState,
    ScheduleConfig,
    build_machine,
    build_schedules,
    power_group_of,
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
    # Расписания по маршрутам и время последнего полива каждого маршрута:
    # по нему расписание решает, не полили ли уже вручную.
    schedules: dict[str, Schedule] = field(default_factory=dict)
    watered_at: dict[str, datetime] = field(default_factory=dict)
    # Предложение поправить расход после замера уровня в баке.
    flow_suggestion: FlowSuggestionState | None = None

    @property
    def is_busy(self) -> bool:
        return self.machine.is_busy or (self.task is not None and not self.task.done())


class MachineRegistry:
    def __init__(self, store: MachineStore, timezone: str = "UTC") -> None:
        self._store = store
        self._timezone = timezone
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
            try:
                schedules = build_schedules(row.id, config, state, self._timezone)
            except Exception:
                # Машина важнее расписания: без расписаний она всё равно поливает по кнопке.
                log.exception("cannot load schedules of machine %s, skipped", row.id)
                schedules = {}
            self._entries[row.id] = MachineEntry(
                row.id,
                config,
                machine,
                schedules=schedules,
                flow_suggestion=state.flow_suggestion,
            )

    # --- Порт MachineRepository ---

    async def get(self, machine_id: str) -> WateringMachine:
        return self.entry(machine_id).machine

    async def save(self, machine: WateringMachine) -> None:
        await self._store.save_state(machine.id, self.state_for(machine.id))

    def state_for(self, machine_id: str) -> MachineState:
        """Состояние машины плюс отметки расписаний: их домен не хранит."""
        entry = self.entry(machine_id)
        state = state_of(entry.machine)
        state.schedule_runs = {
            route_id: schedule.last_run_at
            for route_id, schedule in entry.schedules.items()
            if schedule.last_run_at is not None
        }
        state.flow_suggestion = entry.flow_suggestion
        return state

    # --- Доступ ---

    def entries(self) -> list[MachineEntry]:
        return list(self._entries.values())

    def machines(self) -> list[WateringMachine]:
        """Порт MachineDirectory для проверки состояния."""
        return [entry.machine for entry in self._entries.values()]

    # --- Порты планировщика и очереди ---

    def schedules(self) -> list[Schedule]:
        return [s for entry in self._entries.values() for s in entry.schedules.values()]

    def machine_name(self, machine_id: str) -> str:
        entry = self._entries.get(machine_id)
        return entry.config.name if entry else machine_id

    def last_watering_at(self, machine_id: str, route_id: str) -> datetime | None:
        entry = self._entries.get(machine_id)
        return entry.watered_at.get(route_id) if entry else None

    def power_group(self, machine_id: str) -> PowerGroup:
        return power_group_of(machine_id, {e.id: e.config for e in self._entries.values()})

    async def save_schedules(self, machine_id: str) -> None:
        """Сохранить отметки расписаний, не трогая остальное."""
        await self._store.save_state(machine_id, self.state_for(machine_id))

    def entry(self, machine_id: str) -> MachineEntry:
        try:
            return self._entries[machine_id]
        except KeyError:
            raise UnknownMachineError(f"unknown machine {machine_id!r}") from None

    # --- CRUD конфигурации ---

    async def create(self, config: MachineConfig) -> MachineEntry:
        machine_id = f"m-{uuid.uuid4().hex[:8]}"
        state = MachineState()
        machine = build_machine(machine_id, config, state)
        await self._store.upsert(machine_id, config, state_of(machine))
        entry = MachineEntry(
            machine_id,
            config,
            machine,
            schedules=build_schedules(machine_id, config, state, self._timezone),
        )
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
        state.schedule_runs = {
            route_id: schedule.last_run_at
            for route_id, schedule in old.schedules.items()
            if schedule.last_run_at is not None
        }
        machine = build_machine(machine_id, config, state)
        entry = MachineEntry(
            machine_id,
            config,
            machine,
            last_watering=old.last_watering,
            schedules=build_schedules(machine_id, config, state, self._timezone),
            watered_at=dict(old.watered_at),
            flow_suggestion=old.flow_suggestion,
        )
        self._entries[machine_id] = entry
        await self._store.upsert(machine_id, config, self.state_for(machine_id))
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
        await self._store.upsert(machine_id, config, self.state_for(machine_id))

    async def set_schedule(
        self, machine_id: str, route_id: str, schedule: ScheduleConfig | None
    ) -> MachineEntry:
        """Задать или убрать расписание маршрута. Машину не пересобираем."""
        entry = self.entry(machine_id)
        config = entry.config.model_copy(deep=True)
        for route in config.routes:
            if route.id == route_id:
                route.schedule = schedule
                break
        else:
            raise UnknownRouteError(f"unknown route {route_id!r}")

        entry.config = config
        state = self.state_for(machine_id)
        entry.schedules = build_schedules(machine_id, config, state, self._timezone)
        await self._store.upsert(machine_id, config, state)
        return entry

    async def resolve_flow_suggestion(self, machine_id: str, apply: bool) -> MachineEntry:
        """Принять или отклонить предложение поправить расход.

        Принять - умножить расход во всех замерах маршрутов на коэффициент.
        Задержка и дотек не меняются.
        """
        entry = self.entry(machine_id)
        suggestion = entry.flow_suggestion
        if suggestion is None:
            return entry
        entry.flow_suggestion = None
        if not apply:
            await self._store.save_state(machine_id, self.state_for(machine_id))
            return entry
        config = entry.config.model_copy(deep=True)
        for route in config.routes:
            if route.calibration is not None:
                route.calibration.flow_points = [
                    FlowPointConfig(
                        tank_volume_ml=point.tank_volume_ml,
                        flow_ml_s=point.flow_ml_s * suggestion.factor,
                    )
                    for point in route.calibration.flow_points
                ]
        return await self.update(machine_id, config)

    async def delete(self, machine_id: str) -> None:
        entry = self.entry(machine_id)
        if entry.is_busy:
            raise MachineBusyError(f"machine {machine_id!r} is watering")
        await self._store.delete(machine_id)
        del self._entries[machine_id]
