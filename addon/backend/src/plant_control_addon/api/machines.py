"""REST API машин: CRUD конфигурации и действия.

Конфигурация правится через POST/PUT/DELETE. Состояние (вода, насос, клапаны)
только через действия: полив, стоп, долив, измеренный объём.
"""

import dataclasses
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from plant_control_addon.config import MachineConfig
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


class MachineStatus(BaseModel):
    busy: bool
    tank: TankStatus
    pump: PumpStatus
    valves: dict[str, str]
    supply_is_filled: bool
    last_watering: WateringResultOut | None


class MachineOut(BaseModel):
    id: str
    config: MachineConfig
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


class StopOut(BaseModel):
    errors: list[str]


def machine_out(entry: MachineEntry) -> MachineOut:
    machine = entry.machine
    tank = machine.tank
    pump = machine.pump
    collector = machine.collector
    last = entry.last_watering
    return MachineOut(
        id=entry.id,
        config=entry.config,
        status=MachineStatus(
            busy=entry.is_busy,
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
        ),
    )


router = APIRouter(prefix="/api/machines", tags=["machines"])

# --- CRUD ---


@router.get("")
async def list_machines(registry: Registry) -> list[MachineOut]:
    return [machine_out(entry) for entry in registry.entries()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_machine(config: MachineConfig, registry: Registry, control: Control) -> MachineOut:
    entry = await registry.create(config)
    await control.safe_start(entry.id)
    return machine_out(entry)


@router.get("/{machine_id}")
async def get_machine(machine_id: str, registry: Registry) -> MachineOut:
    return machine_out(registry.entry(machine_id))


@router.put("/{machine_id}")
async def update_machine(
    machine_id: str, config: MachineConfig, registry: Registry, control: Control
) -> MachineOut:
    entry = await registry.update(machine_id, config)
    # Реле могли поменяться: привести новое железо в безопасное состояние.
    await control.safe_start(machine_id)
    return machine_out(entry)


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
async def start_watering(machine_id: str, body: WateringRequest, control: Control) -> PlanOut:
    """Запускает полив в фоне и сразу отвечает планом. Ход полива - в статусе машины."""
    plan = await control.start_watering(machine_id, body.route_id, body.dose_ml)
    return PlanOut(**dataclasses.asdict(plan))


@router.post("/{machine_id}/stop")
async def emergency_stop(machine_id: str, control: Control) -> StopOut:
    errors = await control.emergency_stop(machine_id)
    return StopOut(errors=[str(error) for error in errors])


@router.post("/{machine_id}/tank/refill")
async def refill_tank(
    machine_id: str, body: RefillRequest, registry: Registry, control: Control
) -> MachineOut:
    await control.refill(machine_id, body.volume_ml)
    return machine_out(registry.entry(machine_id))


@router.put("/{machine_id}/tank/volume")
async def set_tank_volume(
    machine_id: str, body: VolumeRequest, registry: Registry, control: Control
) -> MachineOut:
    """Объём измерен на глаз или по датчику: заменить расчётный."""
    await control.set_tank_volume(machine_id, body.volume_ml)
    return machine_out(registry.entry(machine_id))
