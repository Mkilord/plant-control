"""Тесты доски проблем."""

from datetime import UTC, datetime, timedelta

from plant_control.domain.problems import (
    Observation,
    ProblemBoard,
    ProblemKind,
    Severity,
)

T0 = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)

PUMP_GONE = Observation("m-1", ProblemKind.PUMP_ENTITY_MISSING, "switch.pump_1", "нет сущности")
TANK_LOW = Observation("m-1", ProblemKind.TANK_LOW, details="осталось 80 мл")


def test_new_observation_opens_problem() -> None:
    board = ProblemBoard()
    opened, closed = board.observe([PUMP_GONE], T0)
    assert [p.kind for p in opened] == [ProblemKind.PUMP_ENTITY_MISSING]
    assert closed == []
    assert len(board) == 1


def test_same_observation_does_not_open_twice() -> None:
    board = ProblemBoard()
    board.observe([PUMP_GONE], T0)
    opened, closed = board.observe([PUMP_GONE], T0 + timedelta(minutes=1))
    assert opened == [] and closed == []
    assert board.all()[0].opened_at == T0
    assert board.all()[0].last_seen_at == T0 + timedelta(minutes=1)


def test_problem_closes_itself_when_cause_is_gone() -> None:
    board = ProblemBoard()
    board.observe([PUMP_GONE], T0)
    opened, closed = board.observe([], T0 + timedelta(minutes=1))
    assert opened == []
    assert [p.kind for p in closed] == [ProblemKind.PUMP_ENTITY_MISSING]
    assert len(board) == 0


def test_two_valves_are_two_problems() -> None:
    board = ProblemBoard()
    first = Observation("m-1", ProblemKind.VALVE_ENTITY_MISSING, "v1")
    second = Observation("m-1", ProblemKind.VALVE_ENTITY_MISSING, "v2")
    opened, _ = board.observe([first, second], T0)
    assert len(opened) == 2


def test_errors_come_first() -> None:
    board = ProblemBoard()
    board.observe([TANK_LOW, PUMP_GONE], T0)
    assert board.all()[0].kind is ProblemKind.PUMP_ENTITY_MISSING


def test_blocking_problems() -> None:
    board = ProblemBoard()
    board.observe([PUMP_GONE, TANK_LOW], T0)
    blocking = board.blocking_for("m-1", T0)
    assert [p.kind for p in blocking] == [ProblemKind.PUMP_ENTITY_MISSING]
    assert board.for_machine("m-2") == []


def test_valve_problem_blocks_only_its_plant() -> None:
    board = ProblemBoard()
    board.observe([Observation("m-1", ProblemKind.VALVE_ENTITY_MISSING, "v1")], T0)

    assert [p.target for p in board.blocking_for("m-1", T0, {"v1"})] == ["v1"]
    assert board.blocking_for("m-1", T0, {"v2"}) == []
    # Без растения - всё, что мешает хоть какому-то поливу машины.
    assert len(board.blocking_for("m-1", T0)) == 1


def test_pump_problem_blocks_every_plant() -> None:
    board = ProblemBoard()
    board.observe([PUMP_GONE], T0)

    assert len(board.blocking_for("m-1", T0, {"v2"})) == 1


def test_muted_problem_still_blocks() -> None:
    board = ProblemBoard()
    board.observe([PUMP_GONE], T0)
    board.mute(PUMP_GONE.key, T0 + timedelta(days=1))

    assert len(board.blocking_for("m-1", T0)) == 1


def test_acknowledge_keeps_problem_open() -> None:
    board = ProblemBoard()
    board.observe([PUMP_GONE], T0)
    problem = board.acknowledge(PUMP_GONE.key, T0)
    assert problem is not None and problem.acknowledged_at == T0
    assert len(board) == 1


def test_muted_problem_is_hidden_but_still_blocks() -> None:
    board = ProblemBoard()
    board.observe([PUMP_GONE], T0)
    board.mute(PUMP_GONE.key, T0 + timedelta(hours=1))

    assert board.visible(T0) == []
    assert board.blocking_for("m-1", T0)
    # Через час снова видна.
    assert board.visible(T0 + timedelta(hours=2))


def test_unmute() -> None:
    board = ProblemBoard()
    board.observe([PUMP_GONE], T0)
    board.mute(PUMP_GONE.key, T0 + timedelta(hours=1))
    board.unmute(PUMP_GONE.key)
    assert board.visible(T0)


def test_severity_of_kinds() -> None:
    board = ProblemBoard()
    board.observe([TANK_LOW], T0)
    assert board.all()[0].severity is Severity.INFO
    assert not board.all()[0].blocking
