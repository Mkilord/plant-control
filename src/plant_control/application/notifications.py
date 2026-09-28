"""Уведомления и события для Home Assistant.

Ядро не знает, как выглядит уведомление: оно описывает, что случилось
(событие), и решает, стоит ли об этом сообщать. Текст и способ доставки -
дело адаптера.

Два независимых канала:
- события: уходят всегда, из них автоматизации HA строят свою логику;
- уведомления: уходят по правилам (какие виды интересны, тихие часы).
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from plant_control.application.ports import Clock
from plant_control.domain.problems import Problem

log = logging.getLogger(__name__)


class EventKind(Enum):
    WATERING_DONE = "watering_done"
    WATERING_FAILED = "watering_failed"
    PROBLEM_OPENED = "problem_opened"
    PROBLEM_CLOSED = "problem_closed"
    SCHEDULE_SKIPPED = "schedule_skipped"


# Виды, о которых сообщают по умолчанию: остальное видно в интерфейсе.
DEFAULT_KINDS = frozenset(
    {EventKind.WATERING_FAILED, EventKind.PROBLEM_OPENED, EventKind.SCHEDULE_SKIPPED}
)


@dataclass(frozen=True, slots=True)
class Event:
    """Что случилось. urgent - сообщать даже в тихие часы."""

    kind: EventKind
    machine_id: str
    machine_name: str
    at: datetime
    data: dict[str, Any] = field(default_factory=dict)
    urgent: bool = False


class NotifierPort(Protocol):
    """Доставка уведомления человеку."""

    async def send(self, event: Event) -> None: ...


class EventSinkPort(Protocol):
    """Публикация события для автоматизаций."""

    async def publish(self, event: Event) -> None: ...


@dataclass(frozen=True, slots=True)
class NotificationRules:
    """Какие уведомления нужны и когда молчать.

    Тихие часы могут переходить через полночь: с 23:00 до 07:00.
    Срочные события проходят и в тихие часы.
    """

    kinds: frozenset[EventKind] = DEFAULT_KINDS
    quiet_from: time | None = None
    quiet_to: time | None = None
    timezone: str = "UTC"

    def allows(self, event: Event) -> bool:
        if event.kind not in self.kinds:
            return False
        return event.urgent or not self.is_quiet(event.at)

    def is_quiet(self, moment: datetime) -> bool:
        if self.quiet_from is None or self.quiet_to is None:
            return False
        local = moment.astimezone(ZoneInfo(self.timezone)).time()
        if self.quiet_from <= self.quiet_to:
            return self.quiet_from <= local < self.quiet_to
        # Интервал через полночь: снаружи промежутка "с утра до вечера".
        return local >= self.quiet_from or local < self.quiet_to


class NotificationService:
    def __init__(
        self,
        clock: Clock,
        *,
        notifier: NotifierPort | None = None,
        sinks: Sequence[EventSinkPort] = (),
        rules: NotificationRules | None = None,
    ) -> None:
        self._clock = clock
        self._notifier = notifier
        self._sinks = list(sinks)
        self.rules = rules or NotificationRules()

    async def emit(self, event: Event) -> bool:
        """Опубликовать событие и, если правила разрешают, отправить уведомление.

        Возвращает True, если уведомление ушло. Ошибки доставки не роняют полив:
        уведомление - не часть работы машины.
        """
        for sink in self._sinks:
            try:
                await sink.publish(event)
            except Exception:
                log.exception("cannot publish event %s", event.kind.value)

        if self._notifier is None or not self.rules.allows(event):
            return False
        try:
            await self._notifier.send(event)
        except Exception:
            log.exception("cannot send notification %s", event.kind.value)
            return False
        return True

    async def emit_all(self, events: Iterable[Event]) -> None:
        for event in events:
            await self.emit(event)

    # --- Готовые события ---

    def watering_done(
        self, machine_id: str, machine_name: str, route_id: str, dose_ml: float
    ) -> Event:
        return Event(
            kind=EventKind.WATERING_DONE,
            machine_id=machine_id,
            machine_name=machine_name,
            at=self._clock.now(),
            data={"route_id": route_id, "dose_ml": dose_ml},
        )

    def watering_failed(
        self, machine_id: str, machine_name: str, route_id: str, dose_ml: float, error: str
    ) -> Event:
        return Event(
            kind=EventKind.WATERING_FAILED,
            machine_id=machine_id,
            machine_name=machine_name,
            at=self._clock.now(),
            data={"route_id": route_id, "dose_ml": dose_ml, "error": error},
        )

    def problem_opened(self, machine_id: str, machine_name: str, problem: Problem) -> Event:
        return Event(
            kind=EventKind.PROBLEM_OPENED,
            machine_id=machine_id,
            machine_name=machine_name,
            at=self._clock.now(),
            data={
                "problem": problem.kind.value,
                "severity": problem.severity.value,
                "target": problem.target,
                "details": problem.details,
            },
            urgent=problem.blocking,
        )

    def problem_closed(self, machine_id: str, machine_name: str, problem: Problem) -> Event:
        return Event(
            kind=EventKind.PROBLEM_CLOSED,
            machine_id=machine_id,
            machine_name=machine_name,
            at=self._clock.now(),
            data={"problem": problem.kind.value, "target": problem.target},
        )

    def schedule_skipped(
        self, machine_id: str, machine_name: str, route_id: str, reason: str
    ) -> Event:
        return Event(
            kind=EventKind.SCHEDULE_SKIPPED,
            machine_id=machine_id,
            machine_name=machine_name,
            at=self._clock.now(),
            data={"route_id": route_id, "reason": reason},
        )
