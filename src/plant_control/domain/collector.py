"""Коллектор: набор нормально закрытых клапанов, одновременно открыт не больше одного."""

from enum import Enum

from plant_control.domain.errors import (
    AnotherValveOpenError,
    CollectorStateUnknownError,
    InvalidCollectorError,
    UnknownValveError,
    ValveAlreadyOpenError,
)

# Минимум клапанов в коллекторе. Константы в Python пишут заглавными,
# как static final в Java. Язык их не защищает, это соглашение.
MIN_VALVES = 2


class ValveState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    UNKNOWN = "unknown"


# ОБРАЗЕЦ. Клапан - сущность внутри агрегата коллектора.
# Снаружи его методы напрямую не вызывают: всё идёт через Collector,
# потому что правило "открыт только один" знает коллектор, а не клапан.
class Valve:
    def __init__(self, valve_id: str, state: ValveState = ValveState.CLOSED) -> None:
        self._id = valve_id
        self._state = state

    @property
    def id(self) -> str:
        return self._id

    @property
    def state(self) -> ValveState:
        return self._state

    def mark_opened(self) -> None:
        self._state = ValveState.OPEN

    def mark_closed(self) -> None:
        self._state = ValveState.CLOSED

    def mark_unknown(self) -> None:
        self._state = ValveState.UNKNOWN

    def __repr__(self) -> str:
        return f"Valve(id={self._id!r}, state={self._state.name})"


# Корень агрегата. Все изменения клапанов идут через него.
class Collector:
    # list[Valve] - аналог List<Valve>.
    def __init__(self, collector_id: str, valves: list[Valve]) -> None:
        if len(valves) < MIN_VALVES:
            raise InvalidCollectorError(
                f"collector needs at least {MIN_VALVES} valves, got {len(valves)}"
            )
        ids = [valve.id for valve in valves]
        # set убирает повторы, как HashSet: если длина уменьшилась, были дубли.
        if len(set(ids)) != len(ids):
            raise InvalidCollectorError(f"valve ids must be unique, got {ids}")
        self._id = collector_id
        # list(...) - копия, чтобы внешний код не мог поменять наш список.
        self._valves = list(valves)

    @property
    def id(self) -> str:
        return self._id

    @property
    def valve_ids(self) -> list[str]:
        return [valve.id for valve in self._valves]

    @property
    def open_valve_id(self) -> str | None:
        """id открытого клапана или None, если все закрыты."""
        for valve in self._valves:
            if valve.state is ValveState.OPEN:
                return valve.id
        return None

    def valve_state(self, valve_id: str) -> ValveState:
        """Состояние клапана по id. Нужно тестам и сервису."""
        return self._find(valve_id).state

    # --- Проверки ---

    def check_can_open(self, valve_id: str) -> None:
        """Бросает доменную ошибку, если клапан открыть нельзя."""
        valve = self._find(valve_id)
        if any(v.state is ValveState.UNKNOWN for v in self._valves):
            raise CollectorStateUnknownError("state of some valve is unknown")
        if valve.state is ValveState.OPEN:
            raise ValveAlreadyOpenError(f"valve {valve_id!r} is already open")
        if self.open_valve_id is not None:
            raise AnotherValveOpenError(f"valve {self.open_valve_id!r} is open")

    # --- Изменение состояния ---
    # Порт отработал, фиксируем факт. Как у насоса.

    def mark_opened(self, valve_id: str) -> None:
        self._find(valve_id).mark_opened()

    def mark_closed(self, valve_id: str) -> None:
        self._find(valve_id).mark_closed()

    def mark_unknown(self, valve_id: str) -> None:
        self._find(valve_id).mark_unknown()

    # --- Внутреннее ---

    # Метод с подчёркиванием - внутренний, как private.
    def _find(self, valve_id: str) -> Valve:
        for valve in self._valves:
            if valve.id == valve_id:
                return valve
        raise UnknownValveError(f"unknown valve {valve_id!r}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Collector):
            return NotImplemented
        return self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return f"Collector(id={self._id!r}, valves={self._valves!r})"
