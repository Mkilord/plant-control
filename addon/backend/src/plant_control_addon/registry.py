"""Реестр машин и справочников: живые доменные объекты в памяти плюс запись в SQLite.

Почему в памяти: полив длится секунды и минуты, и все запросы в это время должны
видеть один и тот же объект машины. Иначе второй запрос загрузил бы из базы
свежую копию, не знающую о текущем поливе, и правило "один полив за раз"
не сработало бы.

Машина ссылается на записи справочников. Когда запись меняется, реестр
пересобирает все машины, которые её используют.

Реестр реализует порт MachineRepository из ядра.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from plant_control.domain.collector import ValveState
from plant_control.domain.errors import MachineBusyError, UnknownRouteError
from plant_control.domain.machine import WateringMachine
from plant_control.domain.power import PowerGroup
from plant_control.domain.schedule import Schedule

from plant_control_addon.assembly import (
    accept_calibration,
    power_group_of,
    resolve,
    schedule_key,
    schedules_of,
    stale_routes,
    uses,
    with_fingerprints,
)
from plant_control_addon.catalog import (
    KINDS,
    Catalog,
    CatalogItem,
    CatalogItemInUseError,
    CatalogKind,
    new_id,
    parse_item,
)
from plant_control_addon.config import (
    FlowPointConfig,
    FlowSuggestionState,
    MachineConfig,
    MachineSetup,
    MachineState,
    RouteConfig,
    ScheduleConfig,
    ScheduleLinkConfig,
    build_machine,
    state_of,
)
from plant_control_addon.migration import is_legacy, migrate
from plant_control_addon.storage import MachineStore
from plant_control_addon.transfer import (
    ExportBundle,
    ImportPlan,
    ImportPlanItem,
    build_export,
    check_references,
    match_items,
    referenced,
    remap,
)

log = logging.getLogger(__name__)


class UnknownMachineError(Exception):
    pass


class EntityInUseError(ValueError):
    """Сущность HA уже стоит в другой машине: два владельца одного реле - путь к аварии."""


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
    # Как машину хранят и правят: ссылки на справочники.
    config: MachineConfig
    # Та же машина с подставленными записями справочников.
    setup: MachineSetup
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

    @property
    def stale_routes(self) -> frozenset[str]:
        return self.machine.stale_routes


class MachineRegistry:
    def __init__(self, store: MachineStore, timezone: str = "UTC") -> None:
        self._store = store
        self._timezone = timezone
        self._entries: dict[str, MachineEntry] = {}
        self.catalog = Catalog()

    async def load(self) -> None:
        await self._store.open()
        for item_row in await self._store.load_catalog():
            try:
                kind: CatalogKind = _kind(item_row.kind)
                self.catalog.put(kind, item_row.id, parse_item(kind, item_row.config_json))
            except Exception:
                log.exception("cannot load %s %s, skipped", item_row.kind, item_row.id)

        rows = await self._store.load_all()
        raw: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                raw[row.id] = json.loads(row.config_json)
            except ValueError:
                log.exception("cannot parse machine %s, skipped", row.id)
        if any(is_legacy(config) for config in raw.values()):
            await self._migrate(raw)

        for row in rows:
            if row.id not in raw:
                continue
            try:
                config = MachineConfig.model_validate(raw[row.id])
                state = MachineState.model_validate_json(row.state_json)
                filled = with_fingerprints(config, self.catalog)
                entry = self._build(row.id, config=filled, state=state)
            except Exception:
                # Сломанная запись не должна мешать остальным машинам.
                log.exception("cannot load machine %s, skipped", row.id)
                continue
            entry.flow_suggestion = state.flow_suggestion
            self._entries[row.id] = entry
            if filled is not config:
                await self._store.upsert(row.id, filled, self.state_for(row.id))

    async def _migrate(self, raw: dict[str, dict[str, Any]]) -> None:
        migration = migrate(list(raw.items()))
        log.info(
            "moving %d machines to the catalog: %d new items",
            len(migration.machines),
            len(migration.items),
        )
        for kind, item_id, item in migration.items:
            self.catalog.put(kind, item_id, item)
        await self._store.apply_migration(
            [(kind, item_id, item.model_dump_json()) for kind, item_id, item in migration.items],
            {machine_id: json.dumps(config) for machine_id, config in migration.machines.items()},
        )
        raw.update(migration.machines)

    def _build(
        self,
        machine_id: str,
        *,
        config: MachineConfig,
        state: MachineState,
        old: MachineEntry | None = None,
    ) -> MachineEntry:
        """Собрать машину. Бросает ошибку, если машина не сходится со справочником."""
        setup = resolve(config, self.catalog)
        machine = build_machine(machine_id, setup, state, stale_routes(config, self.catalog))
        try:
            schedules = schedules_of(machine_id, config, state, self.catalog, self._timezone)
        except Exception:
            # Машина важнее расписания: без расписаний она всё равно поливает по кнопке.
            log.exception("cannot build schedules of machine %s, skipped", machine_id)
            schedules = {}
        return MachineEntry(
            machine_id,
            config,
            setup,
            machine,
            last_watering=old.last_watering if old else None,
            schedules=schedules,
            watered_at=dict(old.watered_at) if old else {},
            flow_suggestion=old.flow_suggestion if old else None,
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
        state.schedule_runs = _schedule_runs(entry)
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
        entry = self._entries.get(machine_id)
        return power_group_of(machine_id, entry.config if entry else None, self.catalog)

    async def save_schedules(self, machine_id: str) -> None:
        """Сохранить отметки расписаний, не трогая остальное."""
        await self._store.save_state(machine_id, self.state_for(machine_id))

    def entry(self, machine_id: str) -> MachineEntry:
        try:
            return self._entries[machine_id]
        except KeyError:
            raise UnknownMachineError(f"unknown machine {machine_id!r}") from None

    # --- CRUD машин ---

    async def create(self, config: MachineConfig) -> MachineEntry:
        self._check_entities(config, None)
        machine_id = f"m-{uuid.uuid4().hex[:8]}"
        config = with_fingerprints(config, self.catalog)
        entry = self._build(machine_id, config=config, state=MachineState())
        await self._store.upsert(machine_id, config, state_of(entry.machine))
        self._entries[machine_id] = entry
        return entry

    async def update(self, machine_id: str, config: MachineConfig) -> MachineEntry:
        """Новая конфигурация, состояние сохраняется там, где это имеет смысл."""
        old = self.entry(machine_id)
        if old.is_busy:
            raise MachineBusyError(f"machine {machine_id!r} is watering")
        self._check_entities(config, machine_id)
        config = with_fingerprints(config, self.catalog)
        state = state_of(old.machine)
        # Клапаны, которых раньше не было, могли остаться открытыми в железе:
        # считаем их неизвестными, безопасный старт после обновления закроет их.
        known = state.valve_states
        state.valve_states = {
            route.id: known.get(route.id, ValveState.UNKNOWN.value) for route in config.routes
        }
        if type(config.plumbing) is not type(old.config.plumbing):
            state.supply_is_filled = False
        state.schedule_runs = _schedule_runs(old)
        # Расписание растения изменилось - отсчёт с этого момента.
        for route in config.routes:
            try:
                before = schedule_key(old.config.route(route.id), self.catalog)
            except KeyError:
                before = None
            if before != schedule_key(route, self.catalog):
                state.schedule_runs.pop(route.id, None)
        entry = self._build(machine_id, config=config, state=state, old=old)
        self._entries[machine_id] = entry
        await self._store.upsert(machine_id, config, self.state_for(machine_id))
        return entry

    async def copy(
        self,
        machine_id: str,
        name: str,
        pump_entity_id: str,
        valves: dict[str, str],
    ) -> MachineEntry:
        """Копия машины с той же калибровкой. Сущности HA у копии свои."""
        source = self.entry(machine_id)
        data = source.config.model_dump(mode="json")
        data["name"] = name
        data["pump"]["entity_id"] = pump_entity_id
        for route in data["routes"]:
            if route.get("valve_entity_id") is not None:
                if route["id"] not in valves:
                    raise ValueError(f"no valve entity for plant {route['id']!r}")
                route["valve_entity_id"] = valves[route["id"]]
            calibration = route.get("calibration")
            if calibration is not None and not calibration.get("copied_from"):
                calibration["copied_from"] = source.config.name
        return await self.create(MachineConfig.model_validate(data))

    async def set_route_dose(self, machine_id: str, route_id: str, dose_ml: float) -> None:
        """Доза по умолчанию для растения. Машину не пересобираем: расчёт от неё не зависит."""
        entry = self.entry(machine_id)
        config = entry.config.model_copy(deep=True)
        _route(config, route_id).default_dose_ml = dose_ml
        entry.config = config
        entry.setup = resolve(config, self.catalog)
        entry.schedules = schedules_of(
            machine_id, config, self.state_for(machine_id), self.catalog, self._timezone
        )
        await self._store.upsert(machine_id, config, self.state_for(machine_id))

    async def set_schedule(
        self,
        machine_id: str,
        route_id: str,
        schedule: ScheduleConfig | None,
        link: ScheduleLinkConfig | None = None,
    ) -> MachineEntry:
        """Задать своё расписание, привязать расписание из справочника или убрать."""
        entry = self.entry(machine_id)
        if link is not None:
            self.catalog.schedule(link.template)
        config = entry.config.model_copy(deep=True)
        route = _route(config, route_id)
        route.schedule = schedule
        route.schedule_link = link
        entry.config = config
        entry.setup = resolve(config, self.catalog)
        state = self.state_for(machine_id)
        # Новое расписание отсчитывается с этого момента, прошлые сроки не трогаем.
        state.schedule_runs.pop(route_id, None)
        entry.schedules = schedules_of(machine_id, config, state, self.catalog, self._timezone)
        await self._store.upsert(machine_id, config, self.state_for(machine_id))
        return entry

    async def accept_calibration(self, machine_id: str, route_id: str) -> MachineEntry:
        """Оставить калибровку после изменения железа: снять пометку "устарела"."""
        entry = self.entry(machine_id)
        _route(entry.config, route_id)
        config = accept_calibration(entry.config, self.catalog, route_id)
        await self._store.save_calibration(
            machine_id, route_id, "accepted", json.dumps({"accepted": True})
        )
        return await self.update(machine_id, config)

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

    def _check_entities(self, config: MachineConfig, machine_id: str | None) -> None:
        mine = set(config.entities())
        for entry in self._entries.values():
            if entry.id == machine_id:
                continue
            taken = mine & set(entry.config.entities())
            if taken:
                raise EntityInUseError(
                    f"{', '.join(sorted(taken))} already used by machine {entry.config.name!r}"
                )

    # --- Экспорт и импорт ---

    def export(self, machine_ids: list[str] | None = None) -> ExportBundle:
        """Машины (все или выбранные) вместе с их оборудованием и расписаниями."""
        entries = (
            [self.entry(machine_id) for machine_id in machine_ids]
            if machine_ids
            else self.entries()
        )
        return build_export(
            [(entry.id, entry.config, entry.stale_routes) for entry in entries], self.catalog
        )

    def plan_import(self, bundle: ExportBundle) -> ImportPlan:
        """Что произойдёт при импорте. Ничего не меняет."""
        check_references(bundle)
        owners = {
            entity: entry.config.name
            for entry in self._entries.values()
            for entity in entry.config.entities()
        }
        found, missing = match_items(bundle, self.catalog)
        return ImportPlan(
            machines=[
                ImportPlanItem(
                    id=machine.id,
                    name=machine.config.name,
                    plants=len(machine.config.routes),
                    taken={
                        entity: owners[entity]
                        for entity in machine.config.entities()
                        if entity in owners
                    },
                )
                for machine in bundle.machines
            ],
            new_items=len(missing),
            reused_items=len(found),
        )

    async def import_bundle(
        self, bundle: ExportBundle, machine_ids: list[str] | None = None
    ) -> list[MachineEntry]:
        """Импортировать машины (все или выбранные из файла). Реле должны быть свободны."""
        plan = self.plan_import(bundle)
        chosen = [m for m in bundle.machines if machine_ids is None or m.id in set(machine_ids)]
        blocked = [
            item.name for item in plan.machines if item.taken and item.id in {m.id for m in chosen}
        ]
        if blocked:
            raise EntityInUseError(f"relays already used, cannot import: {', '.join(blocked)}")
        needed = {ref for machine in chosen for ref in referenced(machine.config)}
        ids, missing = match_items(bundle, self.catalog)
        for kind, file_id, item in missing:
            if (kind, file_id) in needed:
                ids[(kind, file_id)] = await self.create_item(kind, item)
        created: list[MachineEntry] = []
        for machine in chosen:
            created.append(await self.create(remap(machine.config, ids)))
        return created

    # --- Справочники ---

    def users(self, kind: CatalogKind, item_id: str) -> list[MachineEntry]:
        """Машины, которые используют запись справочника."""
        return [entry for entry in self._entries.values() if uses(entry.config, kind, item_id)]

    async def create_item(self, kind: CatalogKind, item: CatalogItem) -> str:
        item_id = new_id(kind)
        self.catalog.put(kind, item_id, item)
        await self._store.save_catalog_item(kind, item_id, item.model_dump_json())
        return item_id

    async def update_item(
        self,
        kind: CatalogKind,
        item_id: str,
        item: CatalogItem,
        is_busy: Callable[[str], bool] | None = None,
    ) -> list[MachineEntry]:
        """Изменить запись и пересобрать машины, которые её используют.

        Если какая-то из них не собирается с новой записью, ничего не меняется.
        """
        previous = self.catalog.get(kind, item_id)
        affected = self.users(kind, item_id)
        busy = is_busy or (lambda machine_id: self.entry(machine_id).is_busy)
        for entry in affected:
            if busy(entry.id):
                raise MachineBusyError(f"machine {entry.config.name!r} is busy")
        self.catalog.put(kind, item_id, item)
        rebuilt: list[MachineEntry] = []
        try:
            for entry in affected:
                state = self.state_for(entry.id)
                if kind == "schedule":
                    # Правило поменялось: отсчёт сроков у привязанных растений заново.
                    for route in entry.config.routes:
                        link = route.schedule_link
                        if link is not None and link.template == item_id:
                            state.schedule_runs.pop(route.id, None)
                rebuilt.append(self._build(entry.id, config=entry.config, state=state, old=entry))
        except Exception:
            self.catalog.put(kind, item_id, previous)
            raise
        await self._store.save_catalog_item(kind, item_id, item.model_dump_json())
        for entry in rebuilt:
            self._entries[entry.id] = entry
            await self._store.save_state(entry.id, self.state_for(entry.id))
        return rebuilt

    def preview_item(
        self, kind: CatalogKind, item_id: str, item: CatalogItem
    ) -> list[tuple[MachineEntry, frozenset[str]]]:
        """Что будет, если сохранить запись: машины и маршруты, у которых устареет калибровка.

        Ничего не меняет. Для маршрутов, которые уже устарели, не повторяет.
        """
        previous = self.catalog.get(kind, item_id)
        affected = self.users(kind, item_id)
        self.catalog.put(kind, item_id, item)
        try:
            return [
                (entry, stale_routes(entry.config, self.catalog) - entry.stale_routes)
                for entry in affected
            ]
        finally:
            self.catalog.put(kind, item_id, previous)

    async def delete_item(self, kind: CatalogKind, item_id: str) -> None:
        self.catalog.get(kind, item_id)
        users = self.users(kind, item_id)
        if users:
            names = [entry.config.name for entry in users]
            raise CatalogItemInUseError(f"{kind} {item_id!r} is used by: {', '.join(names)}", names)
        self.catalog.remove(kind, item_id)
        await self._store.delete_catalog_item(kind, item_id)


def _route(config: MachineConfig, route_id: str) -> RouteConfig:
    try:
        return config.route(route_id)
    except KeyError:
        raise UnknownRouteError(f"unknown route {route_id!r}") from None


def _schedule_runs(entry: MachineEntry) -> dict[str, datetime]:
    return {
        route_id: schedule.last_run_at
        for route_id, schedule in entry.schedules.items()
        if schedule.last_run_at is not None
    }


def _kind(value: str) -> CatalogKind:
    for kind in KINDS:
        if kind == value:
            return kind
    raise ValueError(f"unknown catalog kind {value!r}")
