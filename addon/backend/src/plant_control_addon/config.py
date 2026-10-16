"""Конфигурация машины (то, что правится через CRUD) и её состояние.

MachineConfig - то, что хранится и правится: ссылки на записи справочников
(тип бака, модель насоса, тип коллектора, группа питания), трубки, растения,
сущности HA, калибровка.
MachineSetup - та же машина с подставленными записями справочников. Её собирает
assembly.resolve, по ней работают сборка домена, полив и калибровка.
Состояние: сколько воды, включён ли насос, открыты ли клапаны. Меняется только
операциями домена (полив, долив, аварийный стоп), через CRUD его не поправить.

build_machine собирает доменную машину из MachineSetup и состояния,
state_of снимает состояние обратно для сохранения.
"""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal, Self

from plant_control.domain.calibration import FlowPoint, FlowProfile
from plant_control.domain.collector import Collector, Valve, ValveState
from plant_control.domain.connection import Connection, Outlet, Route
from plant_control.domain.flow import ConstantFlow, FlowCurve, LinearFlow, TableFlow
from plant_control.domain.machine import WateringMachine
from plant_control.domain.pump import Pump, PumpPassport, PumpState
from plant_control.domain.schedule import DailyTime, IntervalRule, Rule, WeeklyRule
from plant_control.domain.tank import (
    HorizontalCylinder,
    MeasuredTank,
    RectangularTank,
    Tank,
    TankGeometry,
    VerticalCylinder,
)
from plant_control.domain.tuning import FlowSuggestion, FlowTracker
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
    """Насос машины с подставленной моделью."""

    entity_id: str = Field(pattern=ENTITY_PATTERN)
    # Паспортная модель расхода. Нужна только в расширенном режиме (flow_mode="advanced").
    flow: FlowConfig | None = None
    # None - предел работы выключен.
    max_runtime_s: float | None = Field(default=None, gt=0)
    cooldown_s: float = Field(default=0, ge=0)


class PumpBinding(BaseModel):
    """Насос в машине: модель из справочника и реле в HA."""

    model: str = Field(min_length=1)
    entity_id: str = Field(pattern=ENTITY_PATTERN)


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
    """Своё расписание одного растения. dose_ml не задана - берётся доза маршрута."""

    enabled: bool = True
    rule: RuleConfig
    dose_ml: float | None = Field(default=None, gt=0)
    # Сезонная поправка: летом больше, зимой меньше.
    season_factor: float = Field(default=1.0, gt=0)
    # Насколько можно опоздать и всё равно полить (add-on был выключен).
    catch_up_h: float = Field(default=3, ge=0)
    # Не поливать по расписанию, если недавно полили вручную.
    min_gap_h: float = Field(default=6, ge=0)


class ScheduleLinkConfig(BaseModel):
    """Растение поливается по расписанию из справочника."""

    template: str = Field(min_length=1)
    enabled: bool = True


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


class FlowPointConfig(BaseModel):
    tank_volume_ml: float = Field(ge=0)
    flow_ml_s: float = Field(gt=0)


class RouteCalibrationConfig(BaseModel):
    """Результат калибровки маршрута замером (plant_control.domain.calibration).

    Одна точка расхода - расход постоянный, две - зависит от объёма в баке.
    """

    flow_points: list[FlowPointConfig] = Field(min_length=1, max_length=2)
    prime_s: float = Field(default=0, ge=0)
    afterflow_ml: float = Field(default=0, ge=0)
    method: Literal["marks", "timed", "manual"] = "manual"
    calibrated_at: datetime | None = None
    # Разброс точек, %. None - не считался.
    spread_pct: float | None = None
    # Запись в журнале калибровок, из которой взят результат.
    record_id: int | None = None
    # На чём сделан замер: насос, бак, обвязка, трубки (assembly.fingerprint).
    # Не совпадает с текущим - калибровка устарела. None - ещё не посчитан.
    fingerprint: str | None = None
    # Калибровка скопирована вместе с машиной: имя исходной машины.
    copied_from: str | None = None

    def profile(self) -> FlowProfile:
        return FlowProfile(
            points=tuple(FlowPoint(p.tank_volume_ml, p.flow_ml_s) for p in self.flow_points),
            prime_s=self.prime_s,
            afterflow_ml=self.afterflow_ml,
        )


class DirectPlumbingConfig(BaseModel):
    type: Literal["direct"] = "direct"
    back_to_tank_fraction: float = Field(default=0.5, ge=0, le=1)


class CollectorPlumbingConfig(BaseModel):
    type: Literal["collector"] = "collector"
    # Тип коллектора из справочника.
    collector_type: str = Field(min_length=1)
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
    # Высота выхода и поправка нужны только в расширенном режиме.
    outlet_height_mm: float = 0
    correction: float = Field(default=1.0, gt=0)
    # Свой замер маршрута. Нет - маршрут наследует расход базового.
    calibration: RouteCalibrationConfig | None = None
    # Доза по умолчанию: ей поливает кнопка в Home Assistant и интерфейс.
    default_dose_ml: float = Field(default=100, gt=0)
    # Своё расписание или ссылка на расписание из справочника, не то и другое сразу.
    schedule: ScheduleConfig | None = None
    schedule_link: ScheduleLinkConfig | None = None

    @model_validator(mode="after")
    def one_schedule(self) -> Self:
        if self.schedule is not None and self.schedule_link is not None:
            raise ValueError("route has both its own schedule and a schedule from the catalog")
        return self


class TimingsConfig(BaseModel):
    valve_lead_s: float = Field(default=0.5, ge=0)
    valve_lag_s: float = Field(default=0.5, ge=0)


# --- Машина ---


def _check_routes(
    routes: list[RouteConfig],
    plumbing: PlumbingConfig,
    base_route: str | None,
    pump_entity: str,
) -> None:
    ids = [route.id for route in routes]
    if len(set(ids)) != len(ids):
        raise ValueError("route ids must be unique")
    if base_route is not None and base_route not in ids:
        raise ValueError("base_route must be one of the routes")
    valves = [route.valve_entity_id for route in routes]
    if isinstance(plumbing, CollectorPlumbingConfig):
        if any(valve is None for valve in valves):
            raise ValueError("with a collector every route needs valve_entity_id")
        if len(set(valves)) != len(valves):
            raise ValueError("valve entities must be unique")
        if pump_entity in valves:
            raise ValueError("pump and valve cannot share an entity")
    else:
        if len(routes) != 1:
            raise ValueError("without a collector there must be exactly one route")
        if valves[0] is not None:
            raise ValueError("without a collector routes have no valve_entity_id")


class _Routes(BaseModel):
    """Общее у хранимой и собранной конфигурации: обвязка и маршруты."""

    name: str = Field(min_length=1, max_length=100)
    plumbing: PlumbingConfig
    head_model: Literal["start", "mid", "stepwise"] = "mid"
    # calibrated - полив по калибровке маршрутов; advanced - по паспорту насоса и напору.
    flow_mode: Literal["calibrated", "advanced"] = "calibrated"
    # Маршрут, расход которого наследуют маршруты без своего замера.
    # None - первый откалиброванный.
    base_route: str | None = Field(default=None, pattern=ROUTE_ID_PATTERN)
    routes: list[RouteConfig] = Field(min_length=1)

    def route(self, route_id: str) -> RouteConfig:
        for route in self.routes:
            if route.id == route_id:
                return route
        raise KeyError(route_id)

    def base_route_config(self) -> RouteConfig | None:
        """Откалиброванный маршрут, от которого наследуют остальные."""
        if self.base_route is not None:
            route = self.route(self.base_route)
            if route.calibration is not None:
                return route
        return next((route for route in self.routes if route.calibration is not None), None)


class MachineConfig(_Routes):
    """Машина как её хранят и правят: ссылки на справочники плюс своё."""

    tank_type: str = Field(min_length=1)
    pump: PumpBinding
    # Группа питания из справочника. None - машина сама по себе.
    power_group: str | None = None

    @model_validator(mode="after")
    def check_routes(self) -> Self:
        _check_routes(self.routes, self.plumbing, self.base_route, self.pump.entity_id)
        return self

    def entities(self) -> list[str]:
        """Сущности HA машины: насос и клапаны."""
        valves = [route.valve_entity_id for route in self.routes if route.valve_entity_id]
        return [self.pump.entity_id, *valves]


class MachineSetup(_Routes):
    """Машина с подставленными записями справочников. Сама не хранится."""

    tank: TankConfig
    pump: PumpConfig
    timings: TimingsConfig = TimingsConfig()

    @model_validator(mode="after")
    def check_routes(self) -> Self:
        _check_routes(self.routes, self.plumbing, self.base_route, self.pump.entity_id)
        if self.flow_mode == "advanced" and self.pump.flow is None:
            raise ValueError("advanced flow mode needs a pump flow model")
        return self

    def entity_for(self, device_id: str) -> str:
        """Какая сущность HA стоит за насосом или клапаном машины."""
        if device_id == PUMP_ID:
            return self.pump.entity_id
        for route in self.routes:
            if route.id == device_id and route.valve_entity_id is not None:
                return route.valve_entity_id
        raise KeyError(device_id)


class FlowSuggestionState(BaseModel):
    factor: float
    expected_ml: float
    actual_ml: float
    waterings: int
    created_at: datetime

    @classmethod
    def of(cls, suggestion: FlowSuggestion) -> "FlowSuggestionState":
        return cls(
            factor=suggestion.factor,
            expected_ml=suggestion.expected_ml,
            actual_ml=suggestion.actual_ml,
            waterings=suggestion.waterings,
            created_at=suggestion.created_at,
        )


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
    # Автоподстройка: сколько воды по расчёту ушло с последнего замера уровня.
    tracker_expected_ml: float = 0
    tracker_waterings: int = 0
    tracker_valid: bool = True
    # Предложение поправить расход, ждёт решения человека.
    flow_suggestion: FlowSuggestionState | None = None


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


def tube_volume_ml(cfg: ConnectionConfig) -> float:
    return _connection(cfg).dead_volume_ml


def route_profiles(config: _Routes) -> dict[str, FlowProfile]:
    """Профили маршрутов: свой замер или унаследованный от базового маршрута.

    Маршрут без своего замера и без базового в словарь не попадает:
    поливать его нельзя, пока не откалибруют.
    """
    base = config.base_route_config()
    base_profile = base.calibration.profile() if base and base.calibration else None
    base_tube = tube_volume_ml(base.connection) if base else 0.0
    profiles: dict[str, FlowProfile] = {}
    for route in config.routes:
        if route.calibration is not None:
            profiles[route.id] = route.calibration.profile()
        elif base_profile is not None:
            delta = tube_volume_ml(route.connection) - base_tube
            profiles[route.id] = base_profile.inherited(delta)
    return profiles


def _head_model(name: str) -> HeadModel:
    match name:
        case "start":
            return StartLevelHead()
        case "stepwise":
            return StepwiseHead()
        case _:
            return MidDoseHead()


def build_machine(
    machine_id: str,
    config: MachineSetup,
    state: MachineState,
    stale_routes: frozenset[str] = frozenset(),
) -> WateringMachine:
    """Бросает доменные ошибки, если конфигурация физически невозможна
    (например, запас больше бака)."""
    geometry = _geometry(config.tank.geometry)
    capacity = geometry.capacity_ml()
    volume = capacity if state.tank_volume_ml is None else min(state.tank_volume_ml, capacity)
    tank = Tank.with_reserve(geometry, config.tank.reserve_ml, volume)

    calibrated = config.flow_mode == "calibrated"
    pump_flow = config.pump.flow
    pump = Pump(
        PUMP_ID,
        PumpPassport(
            flow=None if calibrated or pump_flow is None else _flow(pump_flow),
            max_runtime=(
                None
                if config.pump.max_runtime_s is None
                else timedelta(seconds=config.pump.max_runtime_s)
            ),
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
        profiles=route_profiles(config) if calibrated else None,
        flow_tracker=FlowTracker(
            expected_ml=state.tracker_expected_ml,
            waterings=state.tracker_waterings,
            valid=state.tracker_valid,
        ),
        stale_routes=stale_routes,
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
        tracker_expected_ml=machine.flow_tracker.expected_ml,
        tracker_waterings=machine.flow_tracker.waterings,
        tracker_valid=machine.flow_tracker.valid,
    )


def rule_of(cfg: RuleConfig, today: date | None = None) -> Rule:
    times = tuple(DailyTime(t.hour, t.minute) for t in cfg.times)
    match cfg:
        case WeeklyRuleConfig():
            return WeeklyRule(days=frozenset(cfg.days), times=times)
        case IntervalRuleConfig():
            # Без даты начала считаем от сегодня: "каждые 3 дня, начиная с сегодня".
            return IntervalRule(cfg.every_days, times, cfg.start_date or today or date.today())
