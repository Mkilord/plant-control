"""Планировщик: превращает решения расписаний в заявки на полив.

Расписание само ничего не запускает - оно только отвечает, что делать сейчас.
Планировщик регулярно спрашивает каждое расписание и, если пора, ставит заявку
в очередь. Дальше решает очередь: чья очередь, хватает ли питания.

Пропуск (проспали окно или недавно полили вручную) тоже отмечается, чтобы
к этому сроку больше не возвращаться, и о нём можно сообщить человеку.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from plant_control.application.notifications import NotificationService
from plant_control.application.ports import Clock
from plant_control.application.queue import RequestSource, WateringQueue, WateringRequest
from plant_control.domain.schedule import Action, Schedule

log = logging.getLogger(__name__)


class ScheduleDirectory(Protocol):
    """Откуда планировщик берёт расписания и историю поливов."""

    def schedules(self) -> Sequence[Schedule]: ...

    def machine_name(self, machine_id: str) -> str: ...

    def last_watering_at(self, machine_id: str, route_id: str) -> datetime | None: ...


# Что сделать после того, как срабатывание отмечено: сохранить отметку.
Persist = Callable[[Schedule], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class TickReport:
    submitted: list[WateringRequest]
    skipped: list[tuple[Schedule, str]]


class SchedulerService:
    def __init__(
        self,
        directory: ScheduleDirectory,
        queue: WateringQueue,
        clock: Clock,
        *,
        notifications: NotificationService | None = None,
        persist: Persist | None = None,
        # Сколько заявка от расписания готова ждать очереди: дольше поливать уже поздно.
        max_wait: timedelta = timedelta(hours=2),
    ) -> None:
        self._directory = directory
        self._queue = queue
        self._clock = clock
        self._notifications = notifications
        self._persist = persist
        self._max_wait = max_wait

    async def tick(self) -> TickReport:
        """Один проход по всем расписаниям."""
        now = self._clock.now()
        submitted: list[WateringRequest] = []
        skipped: list[tuple[Schedule, str]] = []

        for schedule in self._directory.schedules():
            last = self._directory.last_watering_at(schedule.machine_id, schedule.route_id)
            decision = schedule.decide(now, last)
            if decision.action is Action.WAIT or decision.planned_at is None:
                continue

            schedule.mark_handled(decision.planned_at)
            if self._persist is not None:
                try:
                    await self._persist(schedule)
                except Exception:
                    log.exception("cannot save schedule %s", schedule.id)

            if decision.action is Action.RUN:
                request = self._queue.submit(
                    schedule.machine_id,
                    schedule.route_id,
                    decision.dose_ml,
                    source=RequestSource.SCHEDULE,
                    max_wait=self._max_wait,
                )
                submitted.append(request)
                log.info(
                    "schedule %s queued %g ml for %s",
                    schedule.id,
                    decision.dose_ml,
                    schedule.route_id,
                )
            else:
                reason = decision.reason.value if decision.reason else ""
                skipped.append((schedule, reason))
                log.info("schedule %s skipped: %s", schedule.id, reason)
                await self._notify_skip(schedule, reason)

        return TickReport(submitted, skipped)

    async def run(self, interval: float = 30.0) -> None:
        """Фоновая задача. Интервал мелкий: минута расписания не должна проскочить."""
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(interval)

    async def _notify_skip(self, schedule: Schedule, reason: str) -> None:
        if self._notifications is None:
            return
        name = self._directory.machine_name(schedule.machine_id)
        await self._notifications.emit(
            self._notifications.schedule_skipped(
                schedule.machine_id, name, schedule.route_id, reason
            )
        )
