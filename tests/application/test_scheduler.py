"""Тесты планировщика: расписание -> заявка в очереди."""

from datetime import UTC, datetime, timedelta

import pytest

from plant_control.application.notifications import EventKind, NotificationService
from plant_control.application.queue import RequestSource, WateringQueue
from plant_control.application.scheduler import SchedulerService
from plant_control.domain.schedule import DailyTime, Schedule, WeeklyRule
from tests.application.fakes import FakeClock

# 2026-09-28 - понедельник.
MONDAY_8 = datetime(2026, 9, 28, 8, 0, tzinfo=UTC)


class Directory:
    def __init__(self, *schedules: Schedule) -> None:
        self._schedules = list(schedules)
        self.last: dict[tuple[str, str], datetime] = {}

    def schedules(self) -> list[Schedule]:
        return self._schedules

    def machine_name(self, machine_id: str) -> str:
        return "Фикус"

    def last_watering_at(self, machine_id: str, route_id: str) -> datetime | None:
        return self.last.get((machine_id, route_id))


class Runner:
    def __init__(self) -> None:
        self.watered: list[tuple[str, float]] = []

    async def water(self, machine_id: str, route_id: str, dose_ml: float) -> None:
        self.watered.append((route_id, dose_ml))


class Notifier:
    def __init__(self) -> None:
        self.sent: list[EventKind] = []

    async def send(self, event: object) -> None:
        self.sent.append(event.kind)  # type: ignore[attr-defined]


def schedule(**kwargs: object) -> Schedule:
    defaults: dict[str, object] = {
        "machine_id": "m-1",
        "route_id": "main",
        "dose_ml": 120,
        "rule": WeeklyRule(days=frozenset({0}), times=(DailyTime(8, 0),)),
    }
    return Schedule("s-1", **{**defaults, **kwargs})  # type: ignore[arg-type]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(MONDAY_8)


def scheduler(
    clock: FakeClock, directory: Directory, **kwargs: object
) -> tuple[SchedulerService, WateringQueue, Runner]:
    runner = Runner()
    queue = WateringQueue(runner, clock)
    service = SchedulerService(directory, queue, clock, **kwargs)  # type: ignore[arg-type]
    return service, queue, runner


async def test_scheduled_time_creates_a_request(clock: FakeClock) -> None:
    directory = Directory(schedule())
    service, queue, _ = scheduler(clock, directory)

    report = await service.tick()

    assert [r.route_id for r in report.submitted] == ["main"]
    assert queue.queued()[0].source is RequestSource.SCHEDULE
    assert queue.queued()[0].dose_ml == 120


async def test_the_same_slot_is_not_repeated(clock: FakeClock) -> None:
    directory = Directory(schedule())
    service, queue, _ = scheduler(clock, directory)

    await service.tick()
    clock.current += timedelta(minutes=5)
    await service.tick()

    assert len(queue.queued()) == 1


async def test_season_factor_changes_the_dose(clock: FakeClock) -> None:
    directory = Directory(schedule(season_factor=0.5))
    service, queue, _ = scheduler(clock, directory)

    await service.tick()

    assert queue.queued()[0].dose_ml == 60


async def test_recent_manual_watering_skips_the_slot(clock: FakeClock) -> None:
    item = schedule()
    directory = Directory(item)
    directory.last[("m-1", "main")] = MONDAY_8 - timedelta(hours=1)
    notifier = Notifier()
    service, queue, _ = scheduler(
        clock, directory, notifications=NotificationService(clock, notifier=notifier)
    )

    report = await service.tick()

    assert queue.queued() == []
    assert [reason for _, reason in report.skipped] == ["recently_watered"]
    assert notifier.sent == [EventKind.SCHEDULE_SKIPPED]
    # Срок отмечен: к нему больше не вернёмся.
    assert item.last_run_at == MONDAY_8


async def test_long_downtime_skips_instead_of_late_watering(clock: FakeClock) -> None:
    directory = Directory(schedule(catch_up=timedelta(hours=2)))
    clock.current = MONDAY_8 + timedelta(hours=5)
    service, queue, _ = scheduler(clock, directory)

    report = await service.tick()

    assert queue.queued() == []
    assert [reason for _, reason in report.skipped] == ["too_late"]


async def test_disabled_schedule_does_nothing(clock: FakeClock) -> None:
    directory = Directory(schedule(enabled=False))
    service, queue, _ = scheduler(clock, directory)

    report = await service.tick()

    assert report.submitted == []
    assert queue.queued() == []


async def test_handled_slot_is_persisted(clock: FakeClock) -> None:
    saved: list[str] = []

    async def persist(item: Schedule) -> None:
        saved.append(item.id)

    directory = Directory(schedule())
    service, _, _ = scheduler(clock, directory, persist=persist)

    await service.tick()

    assert saved == ["s-1"]
