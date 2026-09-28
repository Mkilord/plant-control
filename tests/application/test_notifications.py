"""Тесты уведомлений: правила отбора, тихие часы и доставка."""

from datetime import UTC, datetime, time

import pytest

from plant_control.application.notifications import (
    Event,
    EventKind,
    NotificationRules,
    NotificationService,
)
from plant_control.domain.problems import Problem, ProblemKind
from tests.application.fakes import FakeClock

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
NIGHT = datetime(2026, 9, 28, 2, 0, tzinfo=UTC)


class FakeNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[Event] = []
        self.fail = fail

    async def send(self, event: Event) -> None:
        if self.fail:
            raise RuntimeError("no connection")
        self.sent.append(event)


class FakeSink:
    def __init__(self) -> None:
        self.published: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.published.append(event)


def problem(kind: ProblemKind, machine_id: str = "m-1") -> Problem:
    return Problem(
        machine_id=machine_id,
        kind=kind,
        target="",
        details="",
        opened_at=T0,
        last_seen_at=T0,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


# --- Правила ---


def test_kind_outside_rules_is_not_sent() -> None:
    rules = NotificationRules(kinds=frozenset({EventKind.WATERING_FAILED}))
    done = Event(EventKind.WATERING_DONE, "m-1", "Фикус", T0)
    failed = Event(EventKind.WATERING_FAILED, "m-1", "Фикус", T0)

    assert not rules.allows(done)
    assert rules.allows(failed)


def test_quiet_hours_hold_back_everything_but_urgent() -> None:
    rules = NotificationRules(
        kinds=frozenset(EventKind),
        quiet_from=time(23, 0),
        quiet_to=time(7, 0),
    )
    calm = Event(EventKind.PROBLEM_OPENED, "m-1", "Фикус", NIGHT)
    urgent = Event(EventKind.PROBLEM_OPENED, "m-1", "Фикус", NIGHT, urgent=True)

    assert rules.is_quiet(NIGHT)
    assert not rules.is_quiet(T0)
    assert not rules.allows(calm)
    assert rules.allows(urgent)


def test_quiet_hours_inside_one_day() -> None:
    rules = NotificationRules(quiet_from=time(10, 0), quiet_to=time(14, 0))

    assert rules.is_quiet(T0)
    assert not rules.is_quiet(NIGHT)


def test_quiet_hours_use_the_given_timezone() -> None:
    # 12:00 UTC - это 15:00 в Москве, то есть уже не тихие часы по местному времени.
    rules = NotificationRules(
        quiet_from=time(22, 0), quiet_to=time(14, 0), timezone="Europe/Moscow"
    )

    assert not rules.is_quiet(T0)
    assert rules.is_quiet(NIGHT)


# --- Доставка ---


async def test_events_go_to_sinks_even_when_notification_is_filtered(clock: FakeClock) -> None:
    notifier = FakeNotifier()
    sink = FakeSink()
    service = NotificationService(
        clock,
        notifier=notifier,
        sinks=[sink],
        rules=NotificationRules(kinds=frozenset({EventKind.WATERING_FAILED})),
    )

    sent = await service.emit(service.watering_done("m-1", "Фикус", "main", 100))

    assert not sent
    assert notifier.sent == []
    assert [event.kind for event in sink.published] == [EventKind.WATERING_DONE]


async def test_failed_watering_is_sent_with_the_error(clock: FakeClock) -> None:
    notifier = FakeNotifier()
    service = NotificationService(clock, notifier=notifier)

    sent = await service.emit(
        service.watering_failed("m-1", "Фикус", "main", 100, "PumpControlError: нет связи")
    )

    assert sent
    assert notifier.sent[0].data["error"] == "PumpControlError: нет связи"
    assert notifier.sent[0].at == T0


async def test_blocking_problem_is_urgent(clock: FakeClock) -> None:
    notifier = FakeNotifier()
    service = NotificationService(
        clock,
        notifier=notifier,
        rules=NotificationRules(quiet_from=time(0, 0), quiet_to=time(23, 59)),
    )

    empty = await service.emit(
        service.problem_opened("m-1", "Фикус", problem(ProblemKind.TANK_EMPTY))
    )
    low = await service.emit(service.problem_opened("m-1", "Фикус", problem(ProblemKind.TANK_LOW)))

    assert empty, "пустой бак блокирует полив, о нём сообщают всегда"
    assert not low, "мало воды - терпит до утра"


async def test_broken_notifier_does_not_break_the_caller(clock: FakeClock) -> None:
    sink = FakeSink()
    service = NotificationService(clock, notifier=FakeNotifier(fail=True), sinks=[sink])

    sent = await service.emit(service.watering_failed("m-1", "Фикус", "main", 100, "boom"))

    assert not sent
    assert len(sink.published) == 1
