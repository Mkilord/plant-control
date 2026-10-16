"""Проблемы: что сейчас мешает поливу или требует внимания.

Проблема не записывается вручную, а вычисляется: проверка смотрит на состояние
машин и выдаёт список активных наблюдений. Доска проблем сравнивает его с тем,
что уже открыто: новое открывается, исчезнувшее закрывается само.

Руками можно только подтвердить ("вижу") и приглушить на время. Снимается проблема
только тогда, когда пропала причина.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ProblemKind(Enum):
    """Виды проблем. blocking - полив по этой машине невозможен, пока не решится."""

    HA_DISCONNECTED = "ha_disconnected"
    PUMP_ENTITY_MISSING = "pump_entity_missing"
    VALVE_ENTITY_MISSING = "valve_entity_missing"
    PUMP_STATE_UNKNOWN = "pump_state_unknown"
    VALVE_STATE_UNKNOWN = "valve_state_unknown"
    PUMP_OVERRUN = "pump_overrun"
    TANK_EMPTY = "tank_empty"
    TANK_LOW = "tank_low"
    WATERING_FAILED = "watering_failed"
    SCHEDULE_SKIPPED = "schedule_skipped"
    CALIBRATION_STALE = "calibration_stale"
    # Реле насоса включилось, когда машина не поливала: add-on его выключил.
    PUMP_UNEXPECTED_ON = "pump_unexpected_on"


SEVERITY: dict[ProblemKind, Severity] = {
    ProblemKind.HA_DISCONNECTED: Severity.ERROR,
    ProblemKind.PUMP_ENTITY_MISSING: Severity.ERROR,
    ProblemKind.VALVE_ENTITY_MISSING: Severity.ERROR,
    ProblemKind.PUMP_STATE_UNKNOWN: Severity.ERROR,
    ProblemKind.VALVE_STATE_UNKNOWN: Severity.ERROR,
    ProblemKind.PUMP_OVERRUN: Severity.ERROR,
    ProblemKind.TANK_EMPTY: Severity.WARNING,
    ProblemKind.TANK_LOW: Severity.INFO,
    ProblemKind.WATERING_FAILED: Severity.WARNING,
    ProblemKind.SCHEDULE_SKIPPED: Severity.INFO,
    ProblemKind.CALIBRATION_STALE: Severity.WARNING,
    ProblemKind.PUMP_UNEXPECTED_ON: Severity.ERROR,
}

# Проблемы, при которых поливать нельзя.
BLOCKING: frozenset[ProblemKind] = frozenset(
    {
        ProblemKind.HA_DISCONNECTED,
        ProblemKind.PUMP_ENTITY_MISSING,
        ProblemKind.VALVE_ENTITY_MISSING,
        ProblemKind.PUMP_STATE_UNKNOWN,
        ProblemKind.VALVE_STATE_UNKNOWN,
        ProblemKind.PUMP_OVERRUN,
        ProblemKind.TANK_EMPTY,
        ProblemKind.CALIBRATION_STALE,
    }
)

# Проблемы одного клапана: мешают поливу только своего растения, остальные поливаются.
# Их target - id маршрута или клапана.
ROUTE_SCOPED: frozenset[ProblemKind] = frozenset(
    {
        ProblemKind.VALVE_ENTITY_MISSING,
        ProblemKind.VALVE_STATE_UNKNOWN,
        ProblemKind.CALIBRATION_STALE,
    }
)


@dataclass(frozen=True, slots=True)
class Observation:
    """Факт, замеченный проверкой прямо сейчас."""

    machine_id: str
    kind: ProblemKind
    # Чего касается: id маршрута или сущности. Нужен, чтобы два клапана не слились в одну проблему.
    target: str = ""
    details: str = ""

    @property
    def key(self) -> tuple[str, ProblemKind, str]:
        return (self.machine_id, self.kind, self.target)


@dataclass(frozen=True, slots=True)
class Problem:
    machine_id: str
    kind: ProblemKind
    target: str
    details: str
    opened_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None = None
    muted_until: datetime | None = None

    @property
    def key(self) -> tuple[str, ProblemKind, str]:
        return (self.machine_id, self.kind, self.target)

    @property
    def severity(self) -> Severity:
        return SEVERITY[self.kind]

    @property
    def blocking(self) -> bool:
        return self.kind in BLOCKING

    @property
    def route_scoped(self) -> bool:
        """Касается одного растения, а не всей машины."""
        return self.kind in ROUTE_SCOPED

    def blocks(self, targets: Collection[str] | None = None) -> bool:
        """Мешает ли поливу. targets - маршрут и его клапан; None - любое растение машины."""
        if not self.blocking:
            return False
        if targets is None or not self.route_scoped:
            return True
        return self.target in targets

    def is_muted(self, now: datetime) -> bool:
        return self.muted_until is not None and now < self.muted_until


ProblemKey = tuple[str, ProblemKind, str]


class ProblemBoard:
    """Открытые проблемы всех машин."""

    def __init__(self, problems: Iterable[Problem] = ()) -> None:
        self._problems: dict[ProblemKey, Problem] = {p.key: p for p in problems}

    def observe(
        self, observations: Iterable[Observation], now: datetime
    ) -> tuple[list[Problem], list[Problem]]:
        """Принять срез наблюдений. Возвращает (открытые заново, закрытые)."""
        seen = {o.key: o for o in observations}
        opened: list[Problem] = []

        for key, observation in seen.items():
            existing = self._problems.get(key)
            if existing is None:
                problem = Problem(
                    machine_id=observation.machine_id,
                    kind=observation.kind,
                    target=observation.target,
                    details=observation.details,
                    opened_at=now,
                    last_seen_at=now,
                )
                self._problems[key] = problem
                opened.append(problem)
            else:
                # Проблема держится: обновляем время и текст, подтверждение не сбрасываем.
                self._problems[key] = replace(
                    existing, last_seen_at=now, details=observation.details or existing.details
                )

        closed = [problem for key, problem in self._problems.items() if key not in seen]
        for problem in closed:
            del self._problems[problem.key]
        return opened, closed

    # --- Чтение ---

    def all(self) -> list[Problem]:
        return sorted(
            self._problems.values(),
            key=lambda p: (p.severity is not Severity.ERROR, p.opened_at),
        )

    def for_machine(self, machine_id: str) -> list[Problem]:
        return [p for p in self.all() if p.machine_id == machine_id]

    def blocking_for(
        self, machine_id: str, now: datetime, targets: Collection[str] | None = None
    ) -> list[Problem]:
        """Проблемы, из-за которых поливать нельзя. Приглушение их не отменяет.

        targets - маршрут и его клапан: тогда проблемы других клапанов не мешают.
        """
        return [p for p in self.for_machine(machine_id) if p.blocks(targets)]

    def visible(self, now: datetime) -> list[Problem]:
        """Проблемы, которые стоит показать и о которых стоит уведомить."""
        return [p for p in self.all() if not p.is_muted(now)]

    # --- Действия пользователя ---

    def acknowledge(self, key: ProblemKey, now: datetime) -> Problem | None:
        problem = self._problems.get(key)
        if problem is None:
            return None
        updated = replace(problem, acknowledged_at=now)
        self._problems[key] = updated
        return updated

    def mute(self, key: ProblemKey, until: datetime) -> Problem | None:
        problem = self._problems.get(key)
        if problem is None:
            return None
        updated = replace(problem, muted_until=until)
        self._problems[key] = updated
        return updated

    def unmute(self, key: ProblemKey) -> Problem | None:
        problem = self._problems.get(key)
        if problem is None:
            return None
        updated = replace(problem, muted_until=None)
        self._problems[key] = updated
        return updated

    def __len__(self) -> int:
        return len(self._problems)


def mute_for(now: datetime, duration: timedelta) -> datetime:
    return now + duration
