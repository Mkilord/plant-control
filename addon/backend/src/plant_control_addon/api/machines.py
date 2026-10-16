"""REST API машин: CRUD конфигурации и действия.

Конфигурация правится через POST/PUT/DELETE. Состояние (вода, насос, клапаны)
только через действия: полив, стоп, долив, измеренный объём.
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from plant_control.domain.errors import MachineBusyError
from pydantic import BaseModel, Field

from plant_control_addon.api.queue_routes import QueueItemOut, queue_item_out
from plant_control_addon.config import (
    ENTITY_PATTERN,
    FlowPointConfig,
    FlowSuggestionState,
    MachineConfig,
    MachineSetup,
    ScheduleConfig,
    ScheduleLinkConfig,
)
from plant_control_addon.controller import Controller
from plant_control_addon.registry import MachineEntry, MachineRegistry


def get_registry(request: Request) -> MachineRegistry:
    registry: MachineRegistry = request.app.state.registry
    return registry


def get_controller(request: Request) -> Controller:
    controller: Controller = request.app.state.controller
    return controller


Registry = Annotated[MachineRegistry, Depends(get_registry)]
Control = Annotated[Controller, Depends(get_controller)]

# --- Схемы ответов ---


class TankStatus(BaseModel):
    volume_ml: float
    usable_ml: float
    capacity_ml: float
    reserve_ml: float
    level_mm: float


class PumpStatus(BaseModel):
    state: str
    started_at: datetime | None
    stopped_at: datetime | None


class WateringResultOut(BaseModel):
    route_id: str
    dose_ml: float
    started_at: datetime
    finished_at: datetime
    ok: bool
    error: str | None


class ScheduleStatus(BaseModel):
    route_id: str
    # Расписание из справочника. None - своё расписание растения.
    template: str | None = None
    enabled: bool
    dose_ml: float
    next_run_at: datetime | None
    last_run_at: datetime | None


class BlockerOut(BaseModel):
    """Проблема, из-за которой полив невозможен. route_scoped - мешает только растению target."""

    kind: str
    target: str
    route_scoped: bool
    details: str


class RouteFlowStatus(BaseModel):
    """Чем считается полив маршрута.

    source: own - свой замер, inherited - расход базового маршрута,
    none - режим калибровки, но замера нет; advanced - паспорт насоса.
    """

    route_id: str
    source: Literal["own", "inherited", "none", "advanced"]
    inherited_from: str | None = None
    flow_points: list[FlowPointConfig] = []
    prime_s: float | None = None
    afterflow_ml: float | None = None
    calibrated_at: datetime | None = None
    # Пора калибровать заново (если включено напоминание).
    due: bool = False
    # Насос, бак или трубки поменялись после замера: поливать нельзя.
    stale: bool = False
    # Калибровка пришла вместе с копией машины: имя исходной машины.
    copied_from: str | None = None


class MachineStatus(BaseModel):
    busy: bool
    # id открытой сессии калибровки.
    calibration_session: str | None = None
    flows: list[RouteFlowStatus] = []
    flow_suggestion: FlowSuggestionState | None = None
    tank: TankStatus
    pump: PumpStatus
    valves: dict[str, str]
    supply_is_filled: bool
    last_watering: WateringResultOut | None
    schedules: list[ScheduleStatus] = []
    queue: list[QueueItemOut] = []
    blockers: list[BlockerOut] = []


class MachineOut(BaseModel):
    id: str
    config: MachineConfig
    # Та же машина с подставленными справочниками: бак, насос, задержки клапанов.
    setup: MachineSetup
    status: MachineStatus


class PlanOut(BaseModel):
    dose_ml: float
    pumped_ml: float
    consumed_ml: float
    level_start_mm: float
    level_end_mm: float
    head_start_mm: float
    head_end_mm: float
    flow_start_ml_s: float
    flow_end_ml_s: float
    duration_s: float


class WateringRequest(BaseModel):
    route_id: str
    dose_ml: float = Field(gt=0)


class RefillRequest(BaseModel):
    # None - долить до полного.
    volume_ml: float | None = Field(default=None, gt=0)


class VolumeRequest(BaseModel):
    volume_ml: float = Field(ge=0)


class StartOut(BaseModel):
    """Полив принят: план и место в очереди."""

    plan: PlanOut
    request: QueueItemOut


class StopOut(BaseModel):
    errors: list[str]


class CopyRequest(BaseModel):
    """Копия машины: своё имя и свои реле, остальное как у исходной."""

    name: str = Field(min_length=1, max_length=100)
    pump_entity_id: str = Field(pattern=ENTITY_PATTERN)
    # Реле клапана для каждого растения (id маршрута -> сущность).
    valves: dict[str, str] = {}


def route_flows(
    entry: MachineEntry, now: datetime, reminder_weeks: int | None
) -> list[RouteFlowStatus]:
    config = entry.config
    machine = entry.machine
    base = config.base_route_config()
    result: list[RouteFlowStatus] = []
    stale = entry.stale_routes
    for route in config.routes:
        if config.flow_mode == "advanced":
            result.append(RouteFlowStatus(route_id=route.id, source="advanced"))
            continue
        profile = machine.profile_for(route.id)
        if profile is None:
            result.append(RouteFlowStatus(route_id=route.id, source="none"))
            continue
        own = route.calibration is not None
        source_route = route if own else base
        calibrated_at = (
            source_route.calibration.calibrated_at
            if source_route and source_route.calibration
            else None
        )
        due = (
            reminder_weeks is not None
            and calibrated_at is not None
            and now - calibrated_at > timedelta(weeks=reminder_weeks)
        )
        result.append(
            RouteFlowStatus(
                route_id=route.id,
                source="own" if own else "inherited",
                inherited_from=None if own or base is None else base.id,
                flow_points=[
                    FlowPointConfig(tank_volume_ml=p.tank_volume_ml, flow_ml_s=p.flow_ml_s)
                    for p in profile.points
                ],
                prime_s=profile.prime_s,
                afterflow_ml=profile.afterflow_ml,
                calibrated_at=calibrated_at,
                due=due,
                stale=route.id in stale,
                copied_from=(
                    source_route.calibration.copied_from
                    if source_route and source_route.calibration
                    else None
                ),
            )
        )
    return result


def machine_out(entry: MachineEntry, control: Controller | None = None) -> MachineOut:
    now = control.now() if control else datetime.now(UTC)
    machine = entry.machine
    tank = machine.tank
    pump = machine.pump
    collector = machine.collector
    last = entry.last_watering
    manager = control.calibration if control else None
    session = manager.active_for(entry.id) if manager else None
    reminder = manager.settings.reminder_weeks if manager else None
    return MachineOut(
        id=entry.id,
        config=entry.config,
        setup=entry.setup,
        status=MachineStatus(
            busy=control.is_busy(entry.id) if control else entry.is_busy,
            calibration_session=session.id if session else None,
            flows=route_flows(entry, now, reminder),
            flow_suggestion=entry.flow_suggestion,
            tank=TankStatus(
                volume_ml=tank.volume_ml,
                usable_ml=tank.usable_volume_ml,
                capacity_ml=tank.geometry.capacity_ml(),
                reserve_ml=tank.unusable_volume_ml,
                level_mm=tank.level_mm,
            ),
            pump=PumpStatus(
                state=pump.state.value, started_at=pump.started_at, stopped_at=pump.stopped_at
            ),
            valves=(
                {v: collector.valve_state(v).value for v in collector.valve_ids}
                if collector
                else {}
            ),
            supply_is_filled=machine.supply_is_filled,
            last_watering=WateringResultOut(**dataclasses.asdict(last)) if last else None,
            schedules=[
                ScheduleStatus(
                    route_id=route_id,
                    template=_template(entry, route_id),
                    enabled=schedule.enabled,
                    dose_ml=schedule.dose_ml,
                    next_run_at=schedule.next_run_at(now),
                    last_run_at=schedule.last_run_at,
                )
                for route_id, schedule in entry.schedules.items()
            ],
            queue=[
                queue_item_out(request, control.queue.position(request.id), control)
                for request in control.queue.for_machine(entry.id)
            ]
            if control
            else [],
            blockers=[
                BlockerOut(
                    kind=problem.kind.value,
                    target=problem.target,
                    route_scoped=problem.route_scoped,
                    details=problem.details,
                )
                for problem in control.blockers(entry.id)
            ]
            if control
            else [],
        ),
    )


def _template(entry: MachineEntry, route_id: str) -> str | None:
    link = entry.config.route(route_id).schedule_link
    return link.template if link else None


router = APIRouter(prefix="/api/machines", tags=["machines"])

# --- CRUD ---


@router.get("")
async def list_machines(registry: Registry, control: Control) -> list[MachineOut]:
    return [machine_out(entry, control) for entry in registry.entries()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_machine(config: MachineConfig, registry: Registry, control: Control) -> MachineOut:
    entry = await registry.create(config)
    await control.safe_start(entry.id)
    await control.recheck()
    return machine_out(entry, control)


@router.post("/{machine_id}/copy", status_code=status.HTTP_201_CREATED)
async def copy_machine(
    machine_id: str, body: CopyRequest, registry: Registry, control: Control
) -> MachineOut:
    """Копия с теми же справочниками, трубками и калибровкой. Перекалибровка не нужна."""
    entry = await registry.copy(machine_id, body.name, body.pump_entity_id, body.valves)
    await control.safe_start(entry.id)
    await control.recheck()
    return machine_out(entry, control)


@router.get("/{machine_id}")
async def get_machine(machine_id: str, registry: Registry, control: Control) -> MachineOut:
    return machine_out(registry.entry(machine_id), control)


@router.put("/{machine_id}")
async def update_machine(
    machine_id: str, config: MachineConfig, registry: Registry, control: Control
) -> MachineOut:
    if control.is_calibrating(machine_id):
        raise MachineBusyError(f"machine {machine_id!r} is being calibrated")
    entry = await registry.update(machine_id, config)
    # Реле могли поменяться: привести новое железо в безопасное состояние.
    await control.safe_start(machine_id)
    # Калибровка могла устареть: показать сразу.
    await control.recheck()
    return machine_out(entry, control)


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_machine(machine_id: str, registry: Registry, control: Control) -> None:
    registry.entry(machine_id)
    await control.emergency_stop(machine_id)
    await registry.delete(machine_id)


# --- Действия ---


@router.post("/{machine_id}/plan")
async def plan_watering(machine_id: str, body: WateringRequest, control: Control) -> PlanOut:
    plan = await control.plan(machine_id, body.route_id, body.dose_ml)
    return PlanOut(**dataclasses.asdict(plan))


@router.post("/{machine_id}/water", status_code=status.HTTP_202_ACCEPTED)
async def start_watering(machine_id: str, body: WateringRequest, control: Control) -> StartOut:
    """Ставит полив в очередь и сразу отвечает планом. Ход полива - в статусе машины."""
    plan, request = await control.start_watering(machine_id, body.route_id, body.dose_ml)
    return StartOut(
        plan=PlanOut(**dataclasses.asdict(plan)),
        request=queue_item_out(request, control.queue.position(request.id), control),
    )


@router.post("/{machine_id}/stop")
async def emergency_stop(machine_id: str, control: Control) -> StopOut:
    errors = await control.emergency_stop(machine_id)
    return StopOut(errors=[str(error) for error in errors])


@router.post("/{machine_id}/tank/refill")
async def refill_tank(
    machine_id: str, body: RefillRequest, registry: Registry, control: Control
) -> MachineOut:
    await control.refill(machine_id, body.volume_ml)
    return machine_out(registry.entry(machine_id), control)


@router.put("/{machine_id}/tank/volume")
async def set_tank_volume(
    machine_id: str, body: VolumeRequest, registry: Registry, control: Control
) -> MachineOut:
    """Объём измерен на глаз или по датчику: заменить расчётный."""
    await control.set_tank_volume(machine_id, body.volume_ml)
    return machine_out(registry.entry(machine_id), control)


# --- Расписание маршрута ---


@router.put("/{machine_id}/routes/{route_id}/schedule")
async def set_schedule(
    machine_id: str,
    route_id: str,
    body: ScheduleConfig,
    registry: Registry,
    control: Control,
) -> MachineOut:
    entry = await registry.set_schedule(machine_id, route_id, body)
    return machine_out(entry, control)


@router.put("/{machine_id}/routes/{route_id}/schedule-link")
async def link_schedule(
    machine_id: str,
    route_id: str,
    body: ScheduleLinkConfig,
    registry: Registry,
    control: Control,
) -> MachineOut:
    """Поливать растение по расписанию из справочника. Своё расписание при этом убирается."""
    entry = await registry.set_schedule(machine_id, route_id, None, body)
    return machine_out(entry, control)


@router.delete("/{machine_id}/routes/{route_id}/schedule")
async def clear_schedule(
    machine_id: str, route_id: str, registry: Registry, control: Control
) -> MachineOut:
    """Убрать расписание растения: и своё, и ссылку на справочник."""
    entry = await registry.set_schedule(machine_id, route_id, None)
    return machine_out(entry, control)


# --- Калибровка после изменения железа ---


@router.post("/{machine_id}/routes/{route_id}/calibration/accept")
async def accept_calibration(
    machine_id: str, route_id: str, registry: Registry, control: Control
) -> MachineOut:
    """Оставить калибровку: изменение железа на расход не влияет. Пишется в журнал."""
    if control.is_busy(machine_id):
        raise MachineBusyError(f"machine {machine_id!r} is busy")
    entry = await registry.accept_calibration(machine_id, route_id)
    await control.recheck()
    return machine_out(entry, control)
