"""Расписание полива.

Два правила: по дням недели ("пн, ср, пт в 08:00") и с интервалом в днях
("каждые 5 дней"). У обоих список времён в сутках, поэтому за день может быть
несколько поливов.

Расписание ничего не запускает само. Оно отвечает на вопрос "что делать сейчас"
чистой функцией от текущего времени, а кто и когда спрашивает - забота application.
Время считается в часовом поясе расписания: пользователь думает про 08:00 у себя дома,
а не про UTC.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from plant_control.domain.errors import InvalidScheduleError

# Дальше этого срока вперёд не заглядываем: защита от правила, которое никогда не сработает.
SEARCH_LIMIT_DAYS = 400


@dataclass(frozen=True, slots=True)
class DailyTime:
    """Время суток, когда срабатывает расписание."""

    hour: int
    minute: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.hour <= 23:
            raise InvalidScheduleError(f"hour must be within 0..23, got {self.hour}")
        if not 0 <= self.minute <= 59:
            raise InvalidScheduleError(f"minute must be within 0..59, got {self.minute}")

    def on(self, day: date, tz: ZoneInfo) -> datetime:
        return datetime.combine(day, time(self.hour, self.minute), tzinfo=tz)


def _check_times(times: tuple[DailyTime, ...]) -> None:
    if not times:
        raise InvalidScheduleError("schedule needs at least one time of day")
    if len(set(times)) != len(times):
        raise InvalidScheduleError("times must not repeat")


@dataclass(frozen=True, slots=True)
class WeeklyRule:
    """По дням недели. 0 - понедельник, 6 - воскресенье (как datetime.weekday)."""

    days: frozenset[int]
    times: tuple[DailyTime, ...]

    def __post_init__(self) -> None:
        if not self.days:
            raise InvalidScheduleError("schedule needs at least one weekday")
        if any(day < 0 or day > 6 for day in self.days):
            raise InvalidScheduleError(f"weekdays must be within 0..6, got {sorted(self.days)}")
        _check_times(self.times)

    def matches(self, day: date) -> bool:
        return day.weekday() in self.days


@dataclass(frozen=True, slots=True)
class IntervalRule:
    """Каждые N дней, считая от даты начала."""

    every_days: int
    times: tuple[DailyTime, ...]
    start_date: date

    def __post_init__(self) -> None:
        if self.every_days < 1:
            raise InvalidScheduleError(f"every_days must be >= 1, got {self.every_days}")
        _check_times(self.times)

    def matches(self, day: date) -> bool:
        if day < self.start_date:
            return False
        return (day - self.start_date).days % self.every_days == 0


Rule = WeeklyRule | IntervalRule


def next_occurrence(rule: Rule, after: datetime, tz: ZoneInfo) -> datetime | None:
    """Ближайшее срабатывание строго позже after."""
    day = after.astimezone(tz).date()
    for offset in range(SEARCH_LIMIT_DAYS):
        current = day + timedelta(days=offset)
        if not rule.matches(current):
            continue
        for moment in sorted(t.on(current, tz) for t in rule.times):
            if moment > after:
                return moment
    return None


def previous_occurrence(rule: Rule, before: datetime, tz: ZoneInfo) -> datetime | None:
    """Последнее срабатывание не позже before. Нужно, чтобы понять, не пропустили ли полив."""
    day = before.astimezone(tz).date()
    for offset in range(SEARCH_LIMIT_DAYS):
        current = day - timedelta(days=offset)
        if not rule.matches(current):
            continue
        for moment in sorted((t.on(current, tz) for t in rule.times), reverse=True):
            if moment <= before:
                return moment
    return None


class Action(Enum):
    """Что делать с расписанием прямо сейчас."""

    WAIT = "wait"  # время не пришло
    RUN = "run"  # пора поливать
    SKIP = "skip"  # время пришло, но полив не нужен: пропускаем и ждём следующего


class SkipReason(Enum):
    TOO_LATE = "too_late"  # проспали окно (add-on не работал)
    RECENTLY_WATERED = "recently_watered"  # недавно полили вручную


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    planned_at: datetime | None = None
    dose_ml: float = 0.0
    reason: SkipReason | None = None


class Schedule:
    """Правило полива одного растения на одной машине."""

    def __init__(
        self,
        schedule_id: str,
        *,
        machine_id: str,
        route_id: str,
        dose_ml: float,
        rule: Rule,
        timezone: str = "UTC",
        enabled: bool = True,
        # Насколько можно опоздать и всё равно полить (add-on был выключен).
        catch_up: timedelta = timedelta(hours=3),
        # Не поливать, если этот маршрут поливали вручную меньше чем столько назад.
        min_gap_after_watering: timedelta = timedelta(hours=6),
        # Сезонная поправка дозы: летом больше, зимой меньше.
        season_factor: float = 1.0,
        last_run_at: datetime | None = None,
    ) -> None:
        if dose_ml <= 0:
            raise InvalidScheduleError(f"dose_ml must be positive, got {dose_ml}")
        if season_factor <= 0:
            raise InvalidScheduleError(f"season_factor must be positive, got {season_factor}")
        if catch_up < timedelta(0) or min_gap_after_watering < timedelta(0):
            raise InvalidScheduleError("catch_up and min_gap_after_watering must not be negative")
        try:
            self._tz = ZoneInfo(timezone)
        except Exception as error:
            raise InvalidScheduleError(f"unknown timezone {timezone!r}") from error

        self._id = schedule_id
        self._machine_id = machine_id
        self._route_id = route_id
        self._dose_ml = dose_ml
        self._rule = rule
        self._timezone = timezone
        self._enabled = enabled
        self._catch_up = catch_up
        self._min_gap = min_gap_after_watering
        self._season_factor = season_factor
        self._last_run_at = last_run_at

    # --- Свойства ---

    @property
    def id(self) -> str:
        return self._id

    @property
    def machine_id(self) -> str:
        return self._machine_id

    @property
    def route_id(self) -> str:
        return self._route_id

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def last_run_at(self) -> datetime | None:
        return self._last_run_at

    @property
    def dose_ml(self) -> float:
        """Доза с сезонной поправкой: столько получит растение."""
        return self._dose_ml * self._season_factor

    def next_run_at(self, now: datetime) -> datetime | None:
        """Когда сработает в следующий раз. None - расписание выключено."""
        if not self._enabled:
            return None
        return next_occurrence(self._rule, now, self._tz)

    # --- Решение ---

    def decide(self, now: datetime, last_watering_at: datetime | None = None) -> Decision:
        """Что делать сейчас. last_watering_at - когда этот маршрут поливали в последний раз."""
        if not self._enabled:
            return Decision(Action.WAIT)

        planned = previous_occurrence(self._rule, now, self._tz)
        if planned is None:
            return Decision(Action.WAIT)
        if self._last_run_at is not None and planned <= self._last_run_at:
            # Это срабатывание уже отработано или пропущено.
            return Decision(Action.WAIT)

        if now - planned > self._catch_up:
            return Decision(Action.SKIP, planned, reason=SkipReason.TOO_LATE)
        if last_watering_at is not None and now - last_watering_at < self._min_gap:
            return Decision(Action.SKIP, planned, reason=SkipReason.RECENTLY_WATERED)
        return Decision(Action.RUN, planned, self.dose_ml)

    def mark_handled(self, planned_at: datetime) -> None:
        """Срабатывание отработано (полито или пропущено): больше к нему не возвращаемся."""
        if self._last_run_at is None or planned_at > self._last_run_at:
            self._last_run_at = planned_at

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def __repr__(self) -> str:
        return (
            f"Schedule(id={self._id!r}, machine={self._machine_id!r}, "
            f"route={self._route_id!r}, enabled={self._enabled})"
        )
