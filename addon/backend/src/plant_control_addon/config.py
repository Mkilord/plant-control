"""Конфигурация машины (то, что правится через CRUD) и её состояние.

Конфигурация: форма бака, насос и его реле, обвязка, маршруты.
Состояние: сколько воды, включён ли насос, открыты ли клапаны. Меняется только
операциями домена (полив, долив, аварийный стоп), через CRUD его не поправить.

build_machine собирает доменную машину из конфигурации и состояния,
state_of снимает состояние обратно для сохранения.
"""

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from plant_control.domain.collector import Collector, Valve, ValveState
from plant_control.domain.connection import Connection, Outlet, Route
from plant_control.domain.flow import ConstantFlow, FlowCurve, LinearFlow, TableFlow
from plant_control.domain.machine import WateringMachine
from plant_control.domain.pump import Pump, PumpPassport, PumpState
from plant_control.domain.tank import (
    HorizontalCylinder,
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


GeometryConfig = Annotated[
    VerticalCylinderConfig | HorizontalCylinderConfig | RectangularTankConfig,
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


# --- Обвязка и маршруты ---


class ConnectionConfig(BaseModel):
    length_mm: float = Field(ge=0)
    inner_radius_mm: float = Field(gt=0)


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


# --- Сборка домена ---


def _geometry(cfg: GeometryConfig) -> TankGeometry:
    match cfg:
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
    return Connection(cfg.length_mm, cfg.inner_radius_mm)


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
