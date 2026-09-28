"""REST API очереди поливов и планировщика.

Очередь нужна, когда машины делят блок питания: заявки ждут своей очереди,
а не запускают шесть насосов разом. Здесь на неё можно посмотреть,
добавить заявку и отменить её.
"""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from plant_control.application.queue import WateringRequest as QueueRequest
from plant_control.application.scheduler import SchedulerService
from pydantic import BaseModel, Field

from plant_control_addon.controller import Controller


def get_controller(request: Request) -> Controller:
    controller: Controller = request.app.state.controller
    return controller


def get_scheduler(request: Request) -> SchedulerService | None:
    scheduler: SchedulerService | None = getattr(request.app.state, "scheduler", None)
    return scheduler


Control = Annotated[Controller, Depends(get_controller)]
Scheduler = Annotated[SchedulerService | None, Depends(get_scheduler)]


class QueueItemOut(BaseModel):
    id: str
    machine_id: str
    route_id: str
    dose_ml: float
    source: str
    state: str
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    # Место в очереди, считая с 1. None - заявка уже не ждёт.
    position: int | None = None


class QueueOut(BaseModel):
    running: list[QueueItemOut]
    queued: list[QueueItemOut]
    history: list[QueueItemOut]


class SubmitRequest(BaseModel):
    machine_id: str
    route_id: str
    dose_ml: float = Field(gt=0)
    # Сколько заявка готова ждать очереди, в минутах. Пусто - ждать сколько угодно.
    max_wait_min: float | None = Field(default=None, gt=0)


class TickOut(BaseModel):
    submitted: list[QueueItemOut]
    skipped: list[str]


def queue_item_out(request: QueueRequest, position: int | None = None) -> QueueItemOut:
    return QueueItemOut(
        id=request.id,
        machine_id=request.machine_id,
        route_id=request.route_id,
        dose_ml=request.dose_ml,
        source=request.source.value,
        state=request.state.value,
        requested_at=request.requested_at,
        started_at=request.started_at,
        finished_at=request.finished_at,
        error=request.error,
        position=position,
    )


router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.get("")
async def show_queue(control: Control) -> QueueOut:
    queue = control.queue
    return QueueOut(
        running=[queue_item_out(r) for r in queue.running()],
        queued=[queue_item_out(r, queue.position(r.id)) for r in queue.queued()],
        history=[queue_item_out(r) for r in queue.history()],
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def submit(body: SubmitRequest, control: Control) -> QueueItemOut:
    """Заявка в обход проверки занятости: встанет в очередь и дождётся своего часа."""
    request = control.queue.submit(
        body.machine_id,
        body.route_id,
        body.dose_ml,
        max_wait=timedelta(minutes=body.max_wait_min) if body.max_wait_min else None,
    )
    return queue_item_out(request, control.queue.position(request.id))


@router.delete("/{request_id}")
async def cancel(request_id: str, control: Control) -> QueueItemOut:
    request = control.queue.cancel(request_id)
    return queue_item_out(request)


schedules_router = APIRouter(prefix="/api/schedules", tags=["schedules"])


class ScheduleOut(BaseModel):
    id: str
    machine_id: str
    machine_name: str
    route_id: str
    enabled: bool
    dose_ml: float
    next_run_at: datetime | None
    last_run_at: datetime | None


@schedules_router.get("")
async def list_schedules(request: Request, control: Control) -> list[ScheduleOut]:
    registry = request.app.state.registry
    now = control.now()
    return [
        ScheduleOut(
            id=schedule.id,
            machine_id=schedule.machine_id,
            machine_name=registry.machine_name(schedule.machine_id),
            route_id=schedule.route_id,
            enabled=schedule.enabled,
            dose_ml=schedule.dose_ml,
            next_run_at=schedule.next_run_at(now),
            last_run_at=schedule.last_run_at,
        )
        for schedule in registry.schedules()
    ]


@schedules_router.post("/check")
async def check_schedules(scheduler: Scheduler) -> TickOut:
    """Пройтись по расписаниям сейчас, не дожидаясь очередного круга."""
    if scheduler is None:
        return TickOut(submitted=[], skipped=[])
    report = await scheduler.tick()
    return TickOut(
        submitted=[queue_item_out(request) for request in report.submitted],
        skipped=[f"{schedule.id}: {reason}" for schedule, reason in report.skipped],
    )
