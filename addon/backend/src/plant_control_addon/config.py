"""Конфигурация машины (то, что правится через CRUD) и её состояние.

Конфигурация: форма бака, насос и его реле, обвязка, маршруты.
Состояние: сколько воды, включён ли насос, открыты ли клапаны. Меняется только
операциями домена (полив, долив, аварийный стоп), через CRUD его не поправить.

build_machine собирает доменную машину из конфигурации и состояния,
state_of снимает состояние обратно для сохранения.
"""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal, Self

from plant_control.domain.collector import Collector, Valve, ValveState
from plant_control.domain.connection import Connection, Outlet, Route
from plant_control.domain.flow import ConstantFlow, FlowCurve, LinearFlow, TableFlow
from plant_control.domain.machine import WateringMachine
from plant_control.domain.power import PowerGroup, solo_group
from plant_control.domain.pump import Pump, PumpPassport, PumpState
from plant_control.domain.schedule import DailyTime, IntervalRule, Rule, Schedule, WeeklyRule
from plant_control.domain.tank import (
    HorizontalCylinder,
    MeasuredTank,
    RectangularTank,
    Tank,
    TankGeometry,
    VerticalCylinder,
)
from plant_control.domain.watering import (
    CollectorPlumbing,
    DirectPlumbing,
    HeadModel,
    MidDoseHead,
    Plumbing,
    StartLevelHead,
    StepwiseHead,
)
from pydantic import BaseModel, Field, model_validator

# id насоса внутри машины. Порты привязаны к одной машине, поэтому id не пересекаются.
PUMP_ID = "pump"
COLLECTOR_ID = "collector"

ENTITY_PATTERN = r"^(switch|input_boolean)\.[a-z0-9_]+$"
ROUTE_ID_PATTERN = r"^[a-z0-9_-]{1,32}$"

# --- Форма бака ---
# Literal в поле shape работает как дискриминатор: по нему pydantic выбирает класс,
# как @JsonTypeInfo в Jackson.


class VerticalCylinderConfig(BaseModel):
    shape: Literal["vertical_cylinder"] = "vertical_cylinder"
    diameter_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)


class HorizontalCylinderConfig(BaseModel):
    shape: Literal["horizontal_cylinder"] = "horizontal_cylinder"
    diameter_mm: float = Field(gt=0)
    length_mm: float = Field(gt=0)


class RectangularTankConfig(BaseModel):
    shape: Literal["rectangular"] = "rectangular"
    width_mm: float = Field(gt=0)
    depth_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)


class MeasuredTankConfig(BaseModel):
    """Бак по замеру: объём до линии налива и высота воды при нём."""

    shape: Literal["measured"] = "measured"
    volume_ml: float = Field(gt=0)
    height_mm: float = Field(gt=0)


GeometryConfig = Annotated[
    MeasuredTankConfig | VerticalCylinderConfig | HorizontalCylinderConfig | RectangularTankConfig,
    Field(discriminator="shape"),
]


class TankConfig(BaseModel):
    geometry: GeometryConfig
    # Сколько воды внизу недоступно погружному насосу.
    reserve_ml: float = Field(default=0, ge=0)


# --- Насос ---


class ConstantFlowConfig(BaseModel):
    model: Literal["constant"] = "constant"
    flow_ml_s: float = Field(gt=0)


class LinearFlowConfig(BaseModel):
    model: Literal["linear"] = "linear"
    max_flow_ml_s: float = Field(gt=0)
    max_head_mm: float = Field(gt=0)


class TableFlowConfig(BaseModel):
    model: Literal["table"] = "table"
    # Точки (напор мм, расход мл/с).
    points: list[tuple[float, float]] = Field(min_length=2)


FlowConfig = Annotated[
    ConstantFlowConfig | LinearFlowConfig | TableFlowConfig,
    Field(discriminator="model"),
]


class PumpConfig(BaseModel):
    entity_id: str = Field(pattern=ENTITY_PATTERN)
    flow: FlowConfig
    max_runtime_s: float = Field(gt=0)
    cooldown_s: float = Field(default=0, ge=0)


# --- Расписание ---


class WeeklyRuleConfig(BaseModel):
    """По дням недели. 0 - понедельник, как в datetime.weekday."""

    type: Literal["weekly"] = "weekly"
    days: list[int] = Field(min_length=1)
    times: list[time] = Field(min_length=1)


class IntervalRuleConfig(BaseModel):
    """Каждые N дней от даты начала."""

    type: Literal["interval"] = "interval"
    every_days: int = Field(ge=1)
    times: list[time] = Field(min_length=1)
    start_date: date | None = None


RuleConfig = Annotated[WeeklyRuleConfig | IntervalRuleConfig, Field(discriminator="type")]


class ScheduleConfig(BaseModel):
    """Расписание одного растения. dose_ml не задана - берётся доза маршрута."""

    enabled: bool = True
    rule: RuleConfig
    dose_ml: float | None = Field(default=None, gt=0)
    # Сезонная поправка: летом больше, зимой меньше.
    season_factor: float = Field(default=1.0, gt=0)
    # Насколько можно опоздать и всё равно полить (add-on был выключен).
    catch_up_h: float = Field(default=3, ge=0)
    # Не поливать по расписанию, если недавно полили вручную.
    min_gap_h: float = Field(default=6, ge=0)


# --- Обвязка и маршруты ---


class ConnectionConfig(BaseModel):
    length_mm: float = Field(ge=0)
    inner_diameter_mm: float = Field(gt=0)

    @model_validator(mode="before")
    @classmethod
    def radius_to_diameter(cls, data: Any) -> Any:
        # Старые записи хранили радиус. Переводим, чтобы не терять сохранённые машины.
        old = isinstance(data, dict) and "inner_radius_mm" in data
        if old and "inner_diameter_mm" not in data:
            data = {**data, "inner_diameter_mm": data["inner_radius_mm"] * 2}
            del data["inner_radius_mm"]
        return data


class DirectPlumbingConfig(BaseModel):
    type: Literal["direct"] = "direct"
    back_to_tank_fraction: float = Field(default=0.5, ge=0, le=1)


class CollectorPlumbingConfig(BaseModel):
    type: Literal["collector"] = "collector"
    supply: ConnectionConfig


PlumbingConfig = Annotated[
    DirectPlumbingConfig | CollectorPlumbingConfig,
    Field(discriminator="type"),
]


class RouteConfig(BaseModel):
    id: str = Field(pattern=ROUTE_ID_PATTERN)
    name: str = ""
    # Реле клапана. Нужно только с коллектором.
    valve_entity_id: str | None = Field(default=None, pattern=ENTITY_PATTERN)
    connection: ConnectionConfig
    outlet_height_mm: float
    correction: float = Field(default=1.0, gt=0)
    # Доза по умолчанию: ей поливает кнопка в Home Assistant и интерфейс.
    default_dose_ml: float = Field(default=100, gt=0)
    schedule: ScheduleConfig | None = None


class TimingsConfig(BaseModel):
    valve_lead_s: float = Field(default=0.5, ge=0)
    valve_lag_s: float = Field(default=0.5, ge=0)


# --- Машина ---


class MachineConfig(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    tank: TankConfig
    pump: PumpConfig
    plumbing: PlumbingConfig
    head_model: Literal["start", "mid", "stepwise"] = "mid"
    routes: list[RouteConfig] = Field(min_length=1)
    timings: TimingsConfig = TimingsConfig()
    # Группа питания: машины одной группы делят блок питания. Пусто - машина сама по себе.
    power_group: str = Field(default="", max_length=32)
    # Сколько машин группы могут поливать разом: 1 - строго по очереди.
    power_limit: int = Field(default=1, ge=1)
    # Пауза между пусками в группе: пусковой ток одного насоса не должен совпасть с другим.
    power_gap_s: float = Field(default=2, ge=0)

    @model_validator(mode="after")
    def check_routes(self) -> Self:
        ids = [route.id for route in self.routes]
        if len(set(ids)) != len(ids):
            raise ValueError("route ids must be unique")
        valves = [route.valve_entity_id for route in self.routes]
        if isinstance(self.plumbing, CollectorPlumbingConfig):
            if any(valve is None for valve in valves):
                raise ValueError("with a collector every route needs valve_entity_id")
            if len(set(valves)) != len(valves):
                raise ValueError("valve entities must be unique")
            if self.pump.entity_id in valves:
                raise ValueError("pump and valve cannot share an entity")
        else:
            if len(self.routes) != 1:
                raise ValueError("without a collector there must be exactly one route")
            if valves[0] is not None:
                raise ValueError("without a collector routes have no valve_entity_id")
        return self

    def entity_for(self, device_id: str) -> str:
        """Какая сущность HA стоит за насосом или клапаном машины."""
        if device_id == PUMP_ID:
            return self.pump.entity_id
        for route in self.routes:
            if route.id == device_id and route.valve_entity_id is not None:
                return route.valve_entity_id
        raise KeyError(device_id)


class MachineState(BaseModel):
    """Состояние для хранения. tank_volume_ml=None - новый бак, считаем полным."""

    tank_volume_ml: float | None = None
    pump_state: str = PumpState.OFF.value
    pump_started_at: datetime | None = None
    pump_stopped_at: datetime | None = None
    valve_states: dict[str, str] = {}
    supply_is_filled: bool = False
    # Отработанные сроки расписаний по маршрутам: чтобы не полить один срок дважды.
    schedule_runs: dict[str, datetime] = {}


# --- Сборка домена ---


def _geometry(cfg: GeometryConfig) -> TankGeometry:
    match cfg:
        case MeasuredTankConfig():
            return MeasuredTank(cfg.volume_ml, cfg.height_mm)
        case VerticalCylinderConfig():
            return VerticalCylinder(cfg.diameter_mm, cfg.height_mm)
        case HorizontalCylinderConfig():
            return HorizontalCylinder(cfg.diameter_mm, cfg.length_mm)
        case RectangularTankConfig():
            return RectangularTank(cfg.width_mm, cfg.depth_mm, cfg.height_mm)


def _flow(cfg: FlowConfig) -> FlowCurve:
    match cfg:
        case ConstantFlowConfig():
            return ConstantFlow(cfg.flow_ml_s)
        case LinearFlowConfig():
            return LinearFlow(cfg.max_flow_ml_s, cfg.max_head_mm)
        case TableFlowConfig():
            return TableFlow(tuple(cfg.points))


def _plumbing(cfg: PlumbingConfig) -> Plumbing:
    match cfg:
        case DirectPlumbingConfig():
            return DirectPlumbing(cfg.back_to_tank_fraction)
        case CollectorPlumbingConfig():
            return CollectorPlumbing(_connection(cfg.supply))


def _connection(cfg: ConnectionConfig) -> Connection:
    return Connection(cfg.length_mm, cfg.inner_diameter_mm / 2)


def _head_model(name: str) -> HeadModel:
    match name:
        case "start":
            return StartLevelHead()
        case "stepwise":
            return StepwiseHead()
        case _:
            return MidDoseHead()


def build_machine(machine_id: str, config: MachineConfig, state: MachineState) -> WateringMachine:
    """Бросает доменные ошибки, если конфигурация физически невозможна
    (например, запас больше бака)."""
    geometry = _geometry(config.tank.geometry)
    capacity = geometry.capacity_ml()
    volume = capacity if state.tank_volume_ml is None else min(state.tank_volume_ml, capacity)
    tank = Tank.with_reserve(geometry, config.tank.reserve_ml, volume)

    pump = Pump(
        PUMP_ID,
        PumpPassport(
            flow=_flow(config.pump.flow),
            max_runtime=timedelta(seconds=config.pump.max_runtime_s),
            cooldown=timedelta(seconds=config.pump.cooldown_s),
        ),
        state=PumpState(state.pump_state),
        started_at=state.pump_started_at,
        stopped_at=state.pump_stopped_at,
    )

    collector = None
    if isinstance(config.plumbing, CollectorPlumbingConfig):
        valves = [
            Valve(route.id, ValveState(state.valve_states.get(route.id, ValveState.CLOSED.value)))
            for route in config.routes
        ]
        collector = Collector(COLLECTOR_ID, valves)

    routes = {
        route.id: Route(
            connection=_connection(route.connection),
            outlet=Outlet(route.outlet_height_mm),
            correction=route.correction,
        )
        for route in config.routes
    }

    return WateringMachine(
        machine_id,
        pump=pump,
        tank=tank,
        head_model=_head_model(config.head_model),
        plumbing=_plumbing(config.plumbing),
        routes=routes,
        collector=collector,
        supply_is_filled=state.supply_is_filled,
    )


def state_of(machine: WateringMachine) -> MachineState:
    collector = machine.collector
    valves = (
        {vid: collector.valve_state(vid).value for vid in collector.valve_ids} if collector else {}
    )
    return MachineState(
        tank_volume_ml=machine.tank.volume_ml,
        pump_state=machine.pump.state.value,
        pump_started_at=machine.pump.started_at,
        pump_stopped_at=machine.pump.stopped_at,
        valve_states=valves,
        supply_is_filled=machine.supply_is_filled,
    )


def _rule(cfg: RuleConfig) -> Rule:
    times = tuple(DailyTime(t.hour, t.minute) for t in cfg.times)
    match cfg:
        case WeeklyRuleConfig():
            return WeeklyRule(days=frozenset(cfg.days), times=times)
        case IntervalRuleConfig():
            # Без даты начала считаем от сегодня: "каждые 3 дня, начиная с сегодня".
            return IntervalRule(cfg.every_days, times, cfg.start_date or date.today())


def build_schedule(
    machine_id: str,
    route: RouteConfig,
    timezone: str,
    last_run_at: datetime | None = None,
) -> Schedule | None:
    """Расписание маршрута. None - расписания нет."""
    cfg = route.schedule
    if cfg is None:
        return None
    return Schedule(
        f"{machine_id}:{route.id}",
        machine_id=machine_id,
        route_id=route.id,
        dose_ml=cfg.dose_ml or route.default_dose_ml,
        rule=_rule(cfg.rule),
        timezone=timezone,
        enabled=cfg.enabled,
        catch_up=timedelta(hours=cfg.catch_up_h),
        min_gap_after_watering=timedelta(hours=cfg.min_gap_h),
        season_factor=cfg.season_factor,
        last_run_at=last_run_at,
    )


def build_schedules(
    machine_id: str, config: MachineConfig, state: MachineState, timezone: str
) -> dict[str, Schedule]:
    schedules = {}
    for route in config.routes:
        schedule = build_schedule(machine_id, route, timezone, state.schedule_runs.get(route.id))
        if schedule is not None:
            schedules[route.id] = schedule
    return schedules


def power_group_of(machine_id: str, configs: dict[str, MachineConfig]) -> PowerGroup:
    """Группа питания машины. Предел берём самый строгий из заявленных её участниками."""
    config = configs.get(machine_id)
    if config is None or not config.power_group:
        return solo_group(machine_id)
    members = [c for c in configs.values() if c.power_group == config.power_group]
    return PowerGroup(
        id=config.power_group,
        name=config.power_group,
        max_concurrent=min(c.power_limit for c in members),
        min_start_gap=timedelta(seconds=max(c.power_gap_s for c in members)),
    )
