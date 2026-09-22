"""Тесты модели коллектора."""

import pytest

from plant_control.domain.collector import Collector, Valve, ValveState
from plant_control.domain.errors import (
    AnotherValveOpenError,
    CollectorStateUnknownError,
    InvalidCollectorError,
    UnknownValveError,
    ValveAlreadyOpenError,
)

CLOSED = ValveState.CLOSED
OPEN = ValveState.OPEN
UNKNOWN = ValveState.UNKNOWN


# Фабрика вместо фикстуры: так удобно задавать разное число клапанов.
def make_collector(*states: ValveState) -> Collector:
    # enumerate даёт пары (номер, элемент), как цикл for с индексом в Java.
    # Выражение в квадратных скобках - list comprehension:
    # собрать список из клапанов v1, v2, ... с заданными состояниями.
    valves = [Valve(f"v{i}", state) for i, state in enumerate(states, start=1)]
    return Collector("collector-1", valves)


# --- Создание ---


def test_new_collector_has_no_open_valve() -> None:
    collector = make_collector(CLOSED, CLOSED)
    assert collector.open_valve_id is None


def test_collector_with_one_valve_is_invalid() -> None:
    with pytest.raises(InvalidCollectorError):
        make_collector(CLOSED)


def test_collector_with_duplicate_valve_ids_is_invalid() -> None:
    with pytest.raises(InvalidCollectorError):
        Collector("c", [Valve("v1"), Valve("v1")])


def test_collector_supports_many_valves() -> None:
    collector = make_collector(*[CLOSED] * 8)
    assert collector.valve_ids == [f"v{i}" for i in range(1, 9)]


# --- Проверки перед открытием ---


def test_closed_valve_can_be_opened_when_others_are_closed() -> None:
    make_collector(CLOSED, CLOSED, CLOSED).check_can_open("v2")


def test_unknown_valve_id() -> None:
    with pytest.raises(UnknownValveError):
        make_collector(CLOSED, CLOSED).check_can_open("v9")


def test_cannot_open_when_another_valve_is_open() -> None:
    with pytest.raises(AnotherValveOpenError):
        make_collector(OPEN, CLOSED).check_can_open("v2")


def test_cannot_open_already_open_valve() -> None:
    with pytest.raises(ValveAlreadyOpenError):
        make_collector(OPEN, CLOSED).check_can_open("v1")


def test_cannot_open_when_some_valve_state_is_unknown() -> None:
    with pytest.raises(CollectorStateUnknownError):
        make_collector(CLOSED, UNKNOWN).check_can_open("v1")


# --- Изменение состояния ---


def test_mark_opened_sets_open_valve() -> None:
    collector = make_collector(CLOSED, CLOSED)
    collector.mark_opened("v2")
    assert collector.open_valve_id == "v2"


def test_mark_closed_clears_open_valve() -> None:
    collector = make_collector(CLOSED, OPEN)
    collector.mark_closed("v2")
    assert collector.open_valve_id is None


def test_mark_unknown_blocks_opening() -> None:
    collector = make_collector(CLOSED, CLOSED)
    collector.mark_unknown("v1")
    assert collector.valve_state("v1") is UNKNOWN
    with pytest.raises(CollectorStateUnknownError):
        collector.check_can_open("v2")


def test_mark_closed_works_from_unknown() -> None:
    collector = make_collector(UNKNOWN, CLOSED)
    collector.mark_closed("v1")
    collector.check_can_open("v2")


def test_mark_on_unknown_valve_id() -> None:
    with pytest.raises(UnknownValveError):
        make_collector(CLOSED, CLOSED).mark_opened("v9")
