"""Очередь поливов.

Зачем: поливы нельзя запускать когда попало. Одна машина за раз поливает одно
растение, а машины с общим блоком питания ограничены группой. Расписания к тому же
любят срабатывать в одно и то же время.

Заявка (ручная или от расписания) встаёт в очередь, а диспетчер запускает её,
когда машина свободна и в группе есть место. Заявку можно отменить, у заявки
от расписания есть срок ожидания: если не дождалась, она не выполняется.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol

from plant_control.application.ports import Clock
from plant_control.domain.errors import UnknownRequestError
from plant_control.domain.power import PowerGroup, solo_group

log = logging.getLogger(__name__)

# Сколько выполненных заявок держать в памяти для показа журнала.
HISTORY_LIMIT = 200


class WateringRunner(Protocol):
    """Кто на самом деле поливает. Обычно сценарий полива."""

    async def water(self, machine_id: str, route_id: str, dose_ml: float) -> None: ...


class RequestSource(Enum):
    MANUAL = "manual"
    SCHEDULE = "schedule"


class RequestState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"  # не дождалась своей очереди
    SKIPPED = "skipped"  # расписание решило не поливать: в очередь не вставала


FINISHED = frozenset(
    {
        RequestState.DONE,
        RequestState.FAILED,
        RequestState.CANCELLED,
        RequestState.EXPIRED,
        RequestState.SKIPPED,
    }
)

# Вызывается для каждой завершённой заявки: так журнал попадает в базу.
FinishedListener = Callable[["WateringRequest"], None]


@dataclass
class WateringRequest:
    id: str
    # Порядковый номер: очередь честная по времени подачи, даже если заявки
    # пришли в одну и ту же миллисекунду.
    seq: int
    machine_id: str
    route_id: str
    dose_ml: float
    source: RequestSource
    requested_at: datetime
    # Сколько заявка готова ждать очереди. None - ждать сколько угодно.
    max_wait: timedelta | None = None
    state: RequestState = RequestState.QUEUED
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

    @property
    def is_finished(self) -> bool:
        return self.state in FINISHED

    def expired_at(self, now: datetime) -> bool:
        return self.max_wait is not None and now - self.requested_at > self.max_wait


# Ручные заявки идут раньше заявок от расписания.
PRIORITY = {RequestSource.MANUAL: 0, RequestSource.SCHEDULE: 1}


@dataclass
class _Running:
    request: WateringRequest
    task: asyncio.Task[None]
    group_id: str


class WateringQueue:
    """Диспетчер поливов. Работает одной фоновой задачей: run()."""

    def __init__(
        self,
        runner: WateringRunner,
        clock: Clock,
        group_of: Callable[[str], PowerGroup] | None = None,
        *,
        tick: float = 0.5,
        history: Iterable["WateringRequest"] = (),
        on_finished: FinishedListener | None = None,
    ) -> None:
        self._runner = runner
        self._clock = clock
        # По умолчанию каждая машина сама себе группа: поливы разных машин не мешают друг другу.
        self._group_of = group_of or solo_group
        self._tick = tick
        self._queued: list[WateringRequest] = []
        self._running: dict[str, _Running] = {}
        # Журнал: сначала новые. history - то, что сохранилось с прошлого запуска.
        self._history: list[WateringRequest] = sorted(
            history, key=lambda r: r.finished_at or r.requested_at, reverse=True
        )[:HISTORY_LIMIT]
        self._on_finished = on_finished
        self._last_start: dict[str, datetime] = {}
        self._wake = asyncio.Event()
        self._next_seq = 0

    # --- Заявки ---

    def submit(
        self,
        machine_id: str,
        route_id: str,
        dose_ml: float,
        source: RequestSource = RequestSource.MANUAL,
        max_wait: timedelta | None = None,
    ) -> WateringRequest:
        self._next_seq += 1
        request = WateringRequest(
            id=uuid.uuid4().hex[:8],
            seq=self._next_seq,
            machine_id=machine_id,
            route_id=route_id,
            dose_ml=dose_ml,
            source=source,
            requested_at=self._clock.now(),
            max_wait=max_wait,
        )
        self._queued.append(request)
        self._wake.set()
        return request

    def record_skipped(
        self,
        machine_id: str,
        route_id: str,
        dose_ml: float,
        reason: str,
        source: RequestSource = RequestSource.SCHEDULE,
    ) -> WateringRequest:
        """Записать в журнал полив, который решили не делать. В очередь он не встаёт."""
        self._next_seq += 1
        request = WateringRequest(
            id=uuid.uuid4().hex[:8],
            seq=self._next_seq,
            machine_id=machine_id,
            route_id=route_id,
            dose_ml=dose_ml,
            source=source,
            requested_at=self._clock.now(),
        )
        self._finish(request, RequestState.SKIPPED, reason)
        return request

    def cancel(self, request_id: str) -> WateringRequest:
        """Отменить заявку: из очереди убрать, идущий полив прервать."""
        for request in self._queued:
            if request.id == request_id:
                self._queued.remove(request)
                self._finish(request, RequestState.CANCELLED)
                return request
        running = self._running.get(request_id)
        if running is not None:
            running.task.cancel()
            return running.request
        raise UnknownRequestError(f"unknown request {request_id!r}")

    def cancel_machine(self, machine_id: str) -> list[WateringRequest]:
        """Отменить всё, что связано с машиной: очередь и текущий полив."""
        cancelled = [r for r in list(self._queued) if r.machine_id == machine_id]
        for request in cancelled:
            self.cancel(request.id)
        for running in list(self._running.values()):
            if running.request.machine_id == machine_id:
                running.task.cancel()
                cancelled.append(running.request)
        return cancelled

    # --- Чтение ---

    def queued(self) -> list[WateringRequest]:
        return list(self._queued)

    def running(self) -> list[WateringRequest]:
        return [item.request for item in self._running.values()]

    def history(self) -> list[WateringRequest]:
        return list(self._history)

    def forget(self, ids: Collection[str]) -> int:
        """Убрать законченные заявки из журнала. Сколько убрано."""
        wanted = set(ids)
        before = len(self._history)
        self._history = [r for r in self._history if r.id not in wanted]
        return before - len(self._history)

    def all(self) -> list[WateringRequest]:
        return self.running() + self.queued() + self.history()

    def find(self, request_id: str) -> WateringRequest:
        for request in self.all():
            if request.id == request_id:
                return request
        raise UnknownRequestError(f"unknown request {request_id!r}")

    def position(self, request_id: str) -> int | None:
        """Место в очереди, считая с 1. None - заявка не в очереди."""
        for index, request in enumerate(self._sorted_queue(), start=1):
            if request.id == request_id:
                return index
        return None

    def for_machine(self, machine_id: str) -> list[WateringRequest]:
        return [r for r in self.running() + self.queued() if r.machine_id == machine_id]

    # --- Работа диспетчера ---

    async def run(self) -> None:
        """Фоновая задача: разбирает очередь, пока её не отменят."""
        while True:
            try:
                self.dispatch()
            except Exception:
                log.exception("watering queue dispatch failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._tick)
            self._wake.clear()

    def dispatch(self) -> None:
        """Запустить всё, что уже можно запустить. Вызывается диспетчером и тестами."""
        now = self._clock.now()
        for request in self._sorted_queue():
            group = self._group_of(request.machine_id)
            if request.expired_at(now) or group.waited_too_long(request.requested_at, now):
                self._queued.remove(request)
                self._finish(request, RequestState.EXPIRED)
                continue
            if self._machine_is_busy(request.machine_id):
                continue
            blocked = group.check_can_start(
                running=self._running_in_group(group.id),
                last_start_at=self._last_start.get(group.id),
                now=now,
            )
            if blocked is not None:
                continue
            self._start(request, group, now)

    # --- Внутреннее ---

    def _sorted_queue(self) -> list[WateringRequest]:
        return sorted(self._queued, key=lambda r: (PRIORITY[r.source], r.seq))

    def _machine_is_busy(self, machine_id: str) -> bool:
        return any(item.request.machine_id == machine_id for item in self._running.values())

    def _running_in_group(self, group_id: str) -> int:
        return sum(1 for item in self._running.values() if item.group_id == group_id)

    def _start(self, request: WateringRequest, group: PowerGroup, now: datetime) -> None:
        self._queued.remove(request)
        request.state = RequestState.RUNNING
        request.started_at = now
        self._last_start[group.id] = now
        task = asyncio.create_task(self._execute(request), name=f"watering-{request.id}")
        self._running[request.id] = _Running(request, task, group.id)

    async def _execute(self, request: WateringRequest) -> None:
        state = RequestState.DONE
        error: str | None = None
        try:
            await self._runner.water(request.machine_id, request.route_id, request.dose_ml)
        except asyncio.CancelledError:
            state = RequestState.CANCELLED
            raise
        except Exception as exc:
            log.warning("watering %s failed: %s", request.id, exc)
            state = RequestState.FAILED
            error = f"{type(exc).__name__}: {exc}"
        finally:
            self._running.pop(request.id, None)
            self._finish(request, state, error)
            # Освободилось место: будим диспетчер, не дожидаясь тика.
            self._wake.set()

    def _finish(
        self, request: WateringRequest, state: RequestState, error: str | None = None
    ) -> None:
        request.state = state
        request.error = error
        request.finished_at = self._clock.now()
        self._history.insert(0, request)
        del self._history[HISTORY_LIMIT:]
        if self._on_finished is not None:
            try:
                self._on_finished(request)
            except Exception:
                log.exception("finished listener failed for %s", request.id)


def groups_by_machine(groups: Iterable[tuple[str, PowerGroup]]) -> Callable[[str], PowerGroup]:
    """Готовая функция поиска группы по машине. Машины без группы получают свою."""
    mapping = dict(groups)

    def resolve(machine_id: str) -> PowerGroup:
        return mapping.get(machine_id) or solo_group(machine_id)

    return resolve
