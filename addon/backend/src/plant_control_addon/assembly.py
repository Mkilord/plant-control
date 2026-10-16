"""Сборка машины из её конфигурации и записей справочников.

Здесь же решается, что калибровка устарела: каждая калибровка помнит отпечаток
того, на чём её сделали (модель насоса, бак, обвязка, трубки). Отпечаток
поменялся - замер больше не отражает железо, и поливать по нему нельзя.
"""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

from plant_control.domain.power import PowerGroup, solo_group
from plant_control.domain.schedule import Schedule

from plant_control_addon.catalog import Catalog, CatalogKind, PowerGroupConfig
from plant_control_addon.config import (
    CollectorPlumbingConfig,
    MachineConfig,
    MachineSetup,
    MachineState,
    PumpConfig,
    RouteConfig,
    TankConfig,
    TimingsConfig,
    rule_of,
)


class CatalogMismatchError(ValueError):
    """Машина не сходится со справочником: например, растений больше, чем выходов."""


def resolve(config: MachineConfig, catalog: Catalog) -> MachineSetup:
    """Подставить записи справочников. Бросает UnknownCatalogItemError и CatalogMismatchError."""
    tank = catalog.tank(config.tank_type)
    pump = catalog.pump(config.pump.model)
    timings = TimingsConfig()
    if isinstance(config.plumbing, CollectorPlumbingConfig):
        collector = catalog.collector(config.plumbing.collector_type)
        if len(config.routes) > collector.outlets:
            raise CatalogMismatchError(
                f"{len(config.routes)} plants, but collector {collector.name!r} "
                f"has {collector.outlets} outlets"
            )
        timings = TimingsConfig(
            valve_lead_s=collector.valve_lead_s, valve_lag_s=collector.valve_lag_s
        )
    if config.power_group is not None:
        catalog.power(config.power_group)
    for route in config.routes:
        if route.schedule_link is not None:
            catalog.schedule(route.schedule_link.template)
    if config.flow_mode == "advanced" and pump.flow is None:
        raise CatalogMismatchError(
            f"advanced flow mode needs a datasheet flow in pump model {pump.name!r}"
        )
    return MachineSetup(
        name=config.name,
        plumbing=config.plumbing,
        head_model=config.head_model,
        flow_mode=config.flow_mode,
        base_route=config.base_route,
        routes=config.routes,
        tank=TankConfig(geometry=tank.geometry, reserve_ml=tank.reserve_ml),
        pump=PumpConfig(
            entity_id=config.pump.entity_id,
            flow=pump.flow,
            max_runtime_s=pump.max_runtime_s,
            cooldown_s=pump.cooldown_s,
        ),
        timings=timings,
    )


# --- Отпечаток калибровки ---


def fingerprint(config: MachineConfig, catalog: Catalog, route_id: str) -> str:
    """Отпечаток железа, на котором калибруют маршрут.

    Входит то, что меняет расход, задержку и дотек: модель насоса, форма бака
    и запас, обвязка, задержки клапанов, трубка подачи и трубка маршрута.
    Не входит: сущности HA, имена, расписания, группа питания, ограничения насоса.
    """
    tank = catalog.tank(config.tank_type)
    parts: dict[str, object] = {
        "pump": config.pump.model,
        "tank": tank.geometry.model_dump(mode="json"),
        "reserve_ml": tank.reserve_ml,
        "plumbing": config.plumbing.type,
        "route": config.route(route_id).connection.model_dump(mode="json"),
    }
    if isinstance(config.plumbing, CollectorPlumbingConfig):
        collector = catalog.collector(config.plumbing.collector_type)
        parts["collector"] = config.plumbing.collector_type
        parts["valve"] = [collector.valve_lead_s, collector.valve_lag_s]
        parts["supply"] = config.plumbing.supply.model_dump(mode="json")
    else:
        parts["back_to_tank"] = config.plumbing.back_to_tank_fraction
    raw = json.dumps(parts, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def stale_routes(config: MachineConfig, catalog: Catalog) -> frozenset[str]:
    """Маршруты, по которым поливать нельзя, пока не откалибруют заново.

    Свой замер устарел - маршрут устарел. Маршрут без своего замера наследует
    базовый: устарел базовый - устарел и он. Своя трубка наследника на это
    не влияет, его профиль и так пересчитывается от базового.
    """
    if config.flow_mode != "calibrated":
        return frozenset()
    stale: set[str] = set()
    for route in config.routes:
        calibration = route.calibration
        if calibration is None or calibration.fingerprint is None:
            continue
        if calibration.fingerprint != fingerprint(config, catalog, route.id):
            stale.add(route.id)
    base = config.base_route_config()
    if base is not None and base.id in stale:
        stale.update(route.id for route in config.routes if route.calibration is None)
    return frozenset(stale)


def with_fingerprints(config: MachineConfig, catalog: Catalog) -> MachineConfig:
    """Проставить отпечаток калибровкам, у которых его ещё нет (новые и старые записи)."""
    if all(r.calibration is None or r.calibration.fingerprint for r in config.routes):
        return config
    config = config.model_copy(deep=True)
    for route in config.routes:
        if route.calibration is not None and route.calibration.fingerprint is None:
            route.calibration.fingerprint = fingerprint(config, catalog, route.id)
    return config


def accept_calibration(config: MachineConfig, catalog: Catalog, route_id: str) -> MachineConfig:
    """Оставить калибровку маршрута как есть: отпечаток берётся от текущего железа.

    Маршрут без своего замера принимает калибровку базового.
    """
    config = config.model_copy(deep=True)
    route = config.route(route_id)
    target = route if route.calibration is not None else config.base_route_config()
    if target is None or target.calibration is None:
        raise CatalogMismatchError(f"route {route_id!r} has no calibration to keep")
    target.calibration.fingerprint = fingerprint(config, catalog, target.id)
    return config


# --- Расписания и группы питания ---


def schedule_of(
    machine_id: str,
    route: RouteConfig,
    catalog: Catalog,
    timezone: str,
    last_run_at: datetime | None = None,
    today: date | None = None,
) -> Schedule | None:
    """Расписание растения: своё или из справочника. None - расписания нет.

    Доза: у расписания из справочника своя доза важнее дозы растения.
    """
    own = route.schedule
    link = route.schedule_link
    if own is not None:
        rule, dose, enabled = own.rule, own.dose_ml, own.enabled
        season, catch_up, min_gap = own.season_factor, own.catch_up_h, own.min_gap_h
    elif link is not None:
        template = catalog.schedule(link.template)
        rule, dose, enabled = template.rule, template.dose_ml, link.enabled
        season, catch_up, min_gap = (
            template.season_factor,
            template.catch_up_h,
            template.min_gap_h,
        )
    else:
        return None
    return Schedule(
        f"{machine_id}:{route.id}",
        machine_id=machine_id,
        route_id=route.id,
        dose_ml=dose or route.default_dose_ml,
        rule=rule_of(rule, today),
        timezone=timezone,
        enabled=enabled,
        catch_up=timedelta(hours=catch_up),
        min_gap_after_watering=timedelta(hours=min_gap),
        season_factor=season,
        last_run_at=last_run_at,
    )


def schedules_of(
    machine_id: str,
    config: MachineConfig,
    state: MachineState,
    catalog: Catalog,
    timezone: str,
    now: datetime | None = None,
) -> dict[str, Schedule]:
    """Расписания растений машины.

    Расписание без отметки отработанного срока (новое или только что изменённое)
    отсчитывается от now: сроки до этого момента не поливаются и не считаются
    пропущенными. Иначе новое расписание сразу записало бы вчерашний срок как
    "поздно", а перенос времени мог бы тут же запустить полив.
    """
    baseline = now or datetime.now(UTC)
    schedules = {}
    for route in config.routes:
        last = state.schedule_runs.get(route.id, baseline)
        schedule = schedule_of(machine_id, route, catalog, timezone, last)
        if schedule is not None:
            schedules[route.id] = schedule
    return schedules


def power_group_of(machine_id: str, config: MachineConfig | None, catalog: Catalog) -> PowerGroup:
    """Группа питания машины. Без группы или с удалённой группой машина сама по себе."""
    if config is None or config.power_group is None:
        return solo_group(machine_id)
    item = catalog.items("power").get(config.power_group)
    if not isinstance(item, PowerGroupConfig):
        return solo_group(machine_id)
    return item.group(config.power_group)


def schedule_key(route: RouteConfig, catalog: Catalog) -> str:
    """Чем определяется расписание растения: меняется - отсчёт начинается заново."""
    if route.schedule is not None:
        return route.schedule.model_dump_json()
    if route.schedule_link is not None:
        template = catalog.items("schedule").get(route.schedule_link.template)
        rule = template.model_dump_json() if template is not None else ""
        return f"{route.schedule_link.model_dump_json()}|{rule}"
    return ""


# --- Кто чем пользуется ---


def uses(config: MachineConfig, kind: CatalogKind, item_id: str) -> bool:
    match kind:
        case "tank":
            return config.tank_type == item_id
        case "pump":
            return config.pump.model == item_id
        case "collector":
            plumbing = config.plumbing
            return (
                isinstance(plumbing, CollectorPlumbingConfig) and plumbing.collector_type == item_id
            )
        case "schedule":
            return any(
                r.schedule_link is not None and r.schedule_link.template == item_id
                for r in config.routes
            )
        case "power":
            return config.power_group == item_id
