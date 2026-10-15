"""REST API мастера калибровки, журнала калибровок и автоподстройки расхода."""

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from plant_control.domain.calibration import CalibrationMethod
from plant_control.domain.errors import CalibrationError
from pydantic import BaseModel, Field

from plant_control_addon.api.machines import Control, MachineOut, Registry, machine_out
from plant_control_addon.calibration import (
    CalibrationManager,
    CalibrationSettings,
    Run,
    Session,
    result_json,
)


def get_manager(request: Request) -> CalibrationManager:
    manager: CalibrationManager = request.app.state.calibration
    return manager


Manager = Annotated[CalibrationManager, Depends(get_manager)]

router = APIRouter(tags=["calibration"])


# --- Схемы ---


class OpenRequest(BaseModel):
    route_id: str
    method: Literal["marks", "timed"]
    # Метки в мл для режима меток.
    marks_ml: list[float] = []


class MarkRequest(BaseModel):
    # Секунд от подтверждения старта. volume_ml = 0 - вода пошла.
    t_s: float = Field(gt=0)
    volume_ml: float = Field(ge=0)


class RunRequest(BaseModel):
    duration_s: float = Field(gt=0)


class VolumeRequest(BaseModel):
    volume_ml: float = Field(ge=0)


class ExcludeRequest(BaseModel):
    excluded: bool


class SaveRequest(BaseModel):
    mode: Literal["replace", "second_level"] = "replace"
    make_base: bool = False


class SuggestionRequest(BaseModel):
    apply: bool


class ResultOut(BaseModel):
    flow_ml_s: float
    prime_s: float
    afterflow_ml: float
    spread_pct: float | None
    duration_s: float
    warnings: list[str]


class RunOut(BaseModel):
    index: int
    started_at: datetime
    tank_volume_ml: float
    marks: list[tuple[float, float]]
    water_started_s: float | None
    planned_s: float | None
    stop_reason: str | None
    stopped_after_s: float | None
    volume_ml: float | None
    result: ResultOut | None
    error: str | None
    excluded: bool
    completed: bool


class SessionOut(BaseModel):
    id: str
    machine_id: str
    route_id: str
    method: str
    targets: list[float]
    state: str
    # Сколько секунд идёт текущий прогон по часам сервера.
    elapsed_s: float | None
    # Через сколько секунд сработает автостоп по времени.
    deadline_in_s: float | None
    runs: list[RunOut]
    result: ResultOut | None
    result_error: str | None
    reference_volume_ml: float | None
    # Можно сохранить как второй уровень: у маршрута есть свой замер при другом объёме.
    second_level_possible: bool
    has_calibration: bool


class HistoryOut(BaseModel):
    id: int
    route_id: str
    method: str
    created_at: datetime
    data: dict[str, Any]


def _run_out(run: Run) -> RunOut:
    result = result_json(run.result)
    return RunOut(
        index=run.index,
        started_at=run.started_at,
        tank_volume_ml=run.tank_volume_ml,
        marks=run.marks,
        water_started_s=run.water_started_s,
        planned_s=run.planned_s,
        stop_reason=run.stop_reason.value if run.stop_reason else None,
        stopped_after_s=run.stopped_after_s,
        volume_ml=run.volume_ml,
        result=ResultOut(**result) if result else None,
        error=run.error,
        excluded=run.excluded,
        completed=run.completed,
    )


def session_out(session: Session, manager: CalibrationManager, control: Control) -> SessionOut:
    result: ResultOut | None = None
    error: str | None = None
    reference: float | None = None
    try:
        raw = result_json(session.result(manager.settings.thresholds()))
        assert raw is not None
        result = ResultOut(**raw)
        reference = session.reference_volume_ml()
    except CalibrationError as exc:
        error = str(exc)

    entry = control.registry.entry(session.machine_id)
    route = entry.config.route(session.route_id)
    second = False
    if route.calibration is not None and reference is not None:
        capacity = entry.machine.tank.geometry.capacity_ml()
        gap = abs(route.calibration.flow_points[0].tank_volume_ml - reference) / capacity * 100
        second = gap >= manager.settings.second_level_min_pct

    elapsed = manager.elapsed_s(session)
    return SessionOut(
        id=session.id,
        machine_id=session.machine_id,
        route_id=session.route_id,
        method=session.method.value,
        targets=session.targets,
        state=session.state.value,
        elapsed_s=elapsed,
        deadline_in_s=manager.deadline_in_s(session),
        runs=[_run_out(run) for run in session.runs],
        result=result,
        result_error=error,
        reference_volume_ml=reference,
        second_level_possible=second,
        has_calibration=route.calibration is not None,
    )


# --- Сессия ---


@router.post("/api/machines/{machine_id}/calibration", status_code=201)
async def open_session(
    machine_id: str, body: OpenRequest, manager: Manager, control: Control
) -> SessionOut:
    session = await manager.open(
        machine_id, body.route_id, CalibrationMethod(body.method), body.marks_ml
    )
    return session_out(session, manager, control)


@router.get("/api/calibration/sessions/{session_id}")
async def get_session(session_id: str, manager: Manager, control: Control) -> SessionOut:
    return session_out(manager.session(session_id), manager, control)


@router.post("/api/calibration/sessions/{session_id}/heartbeat")
async def heartbeat(session_id: str, manager: Manager, control: Control) -> SessionOut:
    return session_out(manager.heartbeat(session_id), manager, control)


@router.post("/api/calibration/sessions/{session_id}/start")
async def start_run(session_id: str, manager: Manager, control: Control) -> SessionOut:
    """Прогон по меткам: насос включён, когда пришёл ответ. От него клиент считает время."""
    return session_out(await manager.start_marks_run(session_id), manager, control)


@router.post("/api/calibration/sessions/{session_id}/run")
async def timed_run(
    session_id: str, body: RunRequest, manager: Manager, control: Control
) -> SessionOut:
    session = await manager.start_timed_run(session_id, body.duration_s)
    return session_out(session, manager, control)


@router.post("/api/calibration/sessions/{session_id}/mark")
async def mark(
    session_id: str, body: MarkRequest, manager: Manager, control: Control
) -> SessionOut:
    session = await manager.mark(session_id, body.t_s, body.volume_ml)
    return session_out(session, manager, control)


@router.post("/api/calibration/sessions/{session_id}/stop")
async def stop(session_id: str, manager: Manager, control: Control) -> SessionOut:
    return session_out(await manager.stop(session_id), manager, control)


@router.post("/api/calibration/sessions/{session_id}/volume")
async def volume(
    session_id: str, body: VolumeRequest, manager: Manager, control: Control
) -> SessionOut:
    session = await manager.submit_volume(session_id, body.volume_ml)
    return session_out(session, manager, control)


@router.post("/api/calibration/sessions/{session_id}/skip-volume")
async def skip_volume(session_id: str, manager: Manager, control: Control) -> SessionOut:
    return session_out(await manager.skip_volume(session_id), manager, control)


@router.put("/api/calibration/sessions/{session_id}/runs/{index}")
async def exclude_run(
    session_id: str, index: int, body: ExcludeRequest, manager: Manager, control: Control
) -> SessionOut:
    session = manager.exclude_run(session_id, index, body.excluded)
    return session_out(session, manager, control)


@router.post("/api/calibration/sessions/{session_id}/save")
async def save(
    session_id: str, body: SaveRequest, manager: Manager, registry: Registry, control: Control
) -> MachineOut:
    machine_id = manager.session(session_id).machine_id
    await manager.save(session_id, body.mode, body.make_base)
    await control.safe_start(machine_id)
    return machine_out(registry.entry(machine_id), control)


@router.delete("/api/calibration/sessions/{session_id}", status_code=204)
async def close_session(session_id: str, manager: Manager) -> None:
    await manager.close(session_id)


# --- Журнал, настройки, автоподстройка ---


@router.get("/api/machines/{machine_id}/calibrations")
async def history(machine_id: str, manager: Manager, registry: Registry) -> list[HistoryOut]:
    registry.entry(machine_id)
    rows = await manager.history(machine_id)
    return [
        HistoryOut(
            id=row.id,
            route_id=row.route_id,
            method=row.method,
            created_at=row.created_at,
            data=json.loads(row.data_json),
        )
        for row in rows
    ]


@router.get("/api/calibration/settings")
async def get_settings(manager: Manager) -> CalibrationSettings:
    return manager.settings


@router.put("/api/calibration/settings")
async def put_settings(body: CalibrationSettings, manager: Manager) -> CalibrationSettings:
    await manager.save_settings(body)
    return manager.settings


@router.post("/api/machines/{machine_id}/flow-suggestion")
async def resolve_suggestion(
    machine_id: str, body: SuggestionRequest, registry: Registry, control: Control
) -> MachineOut:
    entry = await registry.resolve_flow_suggestion(machine_id, body.apply)
    return machine_out(entry, control)
