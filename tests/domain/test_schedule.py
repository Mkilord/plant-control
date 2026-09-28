"""Тесты расписания."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from plant_control.domain.errors import InvalidScheduleError
from plant_control.domain.schedule import (
    Action,
    DailyTime,
    IntervalRule,
    Schedule,
    SkipReason,
    WeeklyRule,
    next_occurrence,
    previous_occurrence,
)

MSK = ZoneInfo("Europe/Moscow")
MON = datetime(2026, 9, 21, 12, 0, tzinfo=MSK)  # понедельник


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=MSK)


# --- Правила ---


def test_weekly_next_occurrence() -> None:
    # Понедельник, среда, пятница в 08:00 и 20:00.
    rule = WeeklyRule(frozenset({0, 2, 4}), (DailyTime(8), DailyTime(20)))
    assert next_occurrence(rule, at(21, 12), MSK) == at(21, 20)
    assert next_occurrence(rule, at(21, 21), MSK) == at(23, 8)


def test_weekly_previous_occurrence() -> None:
    rule = WeeklyRule(frozenset({0, 2, 4}), (DailyTime(8),))
    assert previous_occurrence(rule, at(22, 10), MSK) == at(21, 8)


def test_interval_rule_counts_from_start_date() -> None:
    rule = IntervalRule(every_days=5, times=(DailyTime(8),), start_date=date(2026, 9, 21))
    assert next_occurrence(rule, at(21, 9), MSK) == at(26, 8)
    assert next_occurrence(rule, at(26, 9), MSK) == at(1, 8).replace(month=10)


def test_interval_rule_ignores_days_before_start() -> None:
    rule = IntervalRule(every_days=2, times=(DailyTime(8),), start_date=date(2026, 9, 25))
    assert previous_occurrence(rule, at(24, 23), MSK) is None


def test_time_of_day_is_local_not_utc() -> None:
    rule = WeeklyRule(frozenset({0}), (DailyTime(8),))
    moment = next_occurrence(rule, datetime(2026, 9, 20, 0, 0, tzinfo=UTC), MSK)
    assert moment is not None
    assert moment.astimezone(UTC).hour == 5  # 08:00 в Москве это 05:00 UTC


@pytest.mark.parametrize(
    "build",
    [
        lambda: DailyTime(25),
        lambda: WeeklyRule(frozenset(), (DailyTime(8),)),
        lambda: WeeklyRule(frozenset({9}), (DailyTime(8),)),
        lambda: WeeklyRule(frozenset({0}), ()),
        lambda: IntervalRule(0, (DailyTime(8),), date(2026, 9, 21)),
    ],
)
def test_invalid_rules(build: object) -> None:
    with pytest.raises(InvalidScheduleError):
        build()  # type: ignore[operator]


# --- Решения ---


def make_schedule(**kwargs: object) -> Schedule:
    defaults: dict[str, object] = {
        "machine_id": "m-1",
        "route_id": "main",
        "dose_ml": 100,
        "rule": WeeklyRule(frozenset({0, 2, 4}), (DailyTime(8),)),
        "timezone": "Europe/Moscow",
    }
    defaults.update(kwargs)
    return Schedule("s-1", **defaults)  # type: ignore[arg-type]


def test_waits_before_the_time() -> None:
    schedule = make_schedule(last_run_at=at(21, 8))
    assert schedule.decide(at(21, 12)).action is Action.WAIT


def test_runs_when_time_has_come() -> None:
    decision = make_schedule().decide(at(21, 8))
    assert decision.action is Action.RUN
    assert decision.planned_at == at(21, 8)
    assert decision.dose_ml == pytest.approx(100)


def test_does_not_run_twice_for_the_same_time() -> None:
    schedule = make_schedule()
    decision = schedule.decide(at(21, 8, 30))
    schedule.mark_handled(decision.planned_at or at(21, 8))
    assert schedule.decide(at(21, 9)).action is Action.WAIT


def test_skips_when_too_late() -> None:
    schedule = make_schedule(catch_up=timedelta(hours=2))
    decision = schedule.decide(at(21, 11))
    assert decision.action is Action.SKIP
    assert decision.reason is SkipReason.TOO_LATE


def test_skips_after_manual_watering() -> None:
    schedule = make_schedule(min_gap_after_watering=timedelta(hours=6))
    decision = schedule.decide(at(21, 8), last_watering_at=at(21, 5))
    assert decision.action is Action.SKIP
    assert decision.reason is SkipReason.RECENTLY_WATERED


def test_old_manual_watering_does_not_block() -> None:
    schedule = make_schedule(min_gap_after_watering=timedelta(hours=6))
    assert schedule.decide(at(21, 8), last_watering_at=at(20, 20)).action is Action.RUN


def test_season_factor_changes_dose() -> None:
    schedule = make_schedule(season_factor=1.5)
    assert schedule.decide(at(21, 8)).dose_ml == pytest.approx(150)


def test_disabled_schedule_waits_and_has_no_next_run() -> None:
    schedule = make_schedule(enabled=False)
    assert schedule.decide(at(21, 8)).action is Action.WAIT
    assert schedule.next_run_at(at(21, 8)) is None


def test_next_run_at() -> None:
    assert make_schedule().next_run_at(MON) == at(23, 8)


def test_invalid_schedule_values() -> None:
    with pytest.raises(InvalidScheduleError):
        make_schedule(dose_ml=0)
    with pytest.raises(InvalidScheduleError):
        make_schedule(timezone="Nowhere/Nothing")
