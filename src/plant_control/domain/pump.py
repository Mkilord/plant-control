"""Насос: паспорт, состояния, правила включения и выключения."""

# Аналог import в Java. Импортируем только то, что используем.
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from plant_control.domain.errors import (
    InvalidPumpPassportError,
    PumpAlreadyRunningError,
    PumpCoolingDownError,
    PumpRuntimeExceededError,
    PumpStateUnknownError,
)
from plant_control.domain.flow import FlowCurve


# Аналог enum в Java. Значения можно не использовать, важны сами члены.
class PumpState(Enum):
    OFF = "off"
    ON = "on"
    UNKNOWN = "unknown"


# Аналог record в Java.
# frozen=True - поля нельзя менять после создания (как final).
# slots=True - фиксированный набор полей, меньше памяти, нельзя добавить поле на лету.
@dataclass(frozen=True, slots=True)
class PumpPassport:
    # Поля объявляются с типом. Конструктор генерируется автоматически
    # в том же порядке: PumpPassport(flow=..., max_runtime=..., cooldown=...)
    # flow - модель расхода насоса (flow.py): постоянная, линейная или табличная.
    flow: FlowCurve
    max_runtime: timedelta
    cooldown: timedelta

    # Вызывается сразу после сгенерированного конструктора.
    # Аналог компактного конструктора record: здесь проверяем значения.
    def __post_init__(self) -> None:
        if self.max_runtime <= timedelta(0):
            raise InvalidPumpPassportError(f"max_runtime must be positive, got {self.max_runtime}")
        if self.cooldown < timedelta(0):
            raise InvalidPumpPassportError(f"cooldown must be non-negative, got {self.cooldown}")


# Сущность. Обычный класс, а не dataclass: у сущности есть идентичность (id),
# и сравнивать два насоса надо по id, а не по всем полям.
class Pump:
    # Конструктор. self - аналог this, передаётся явно первым аргументом.
    # "X | None" - аналог Optional<X>. "= None" - значение по умолчанию.
    def __init__(
        self,
        pump_id: str,
        passport: PumpPassport,
        state: PumpState = PumpState.OFF,
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
    ) -> None:
        # Подчёркивание в начале имени - соглашение "не трогать снаружи" (аналог private).
        # Язык доступ не запрещает, это договорённость.
        self._id = pump_id
        self._passport = passport
        self._state = state
        self._started_at = started_at
        self._stopped_at = stopped_at

    # @property - геттер, который вызывается без скобок: pump.id, а не pump.id().
    # Сеттера нет, значит снаружи поле только для чтения.
    @property
    def id(self) -> str:
        return self._id

    @property
    def passport(self) -> PumpPassport:
        return self._passport

    @property
    def state(self) -> PumpState:
        return self._state

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    @property
    def stopped_at(self) -> datetime | None:
        return self._stopped_at

    # --- Проверки ---

    def check_can_start(self, now: datetime, duration: timedelta) -> None:
        if self._state is PumpState.ON:
            raise PumpAlreadyRunningError("Pump is already running.")

        if self._state is PumpState.UNKNOWN:
            raise PumpStateUnknownError("Pump state is unknown.")

        if self._stopped_at is not None:
            elapsed = now - self._stopped_at
            if elapsed < self._passport.cooldown:
                raise PumpCoolingDownError("Pump is cooling down.")

        if duration > self._passport.max_runtime:
            raise PumpRuntimeExceededError("Pump runtime exceeded.")

    def is_overrun(self, now: datetime) -> bool:
        if self._state is PumpState.ON and self._started_at is not None:
            return now - self._started_at > self._passport.max_runtime
        return False

    # --- Изменение состояния ---

    def mark_started(self, now: datetime) -> None:
        self._state = PumpState.ON
        self._started_at = now

    def mark_stopped(self, now: datetime) -> None:
        self._state = PumpState.OFF
        self._stopped_at = now

    def mark_unknown(self) -> None:
        self._state = PumpState.UNKNOWN

    # --- Идентичность ---

    # Аналог equals(). Сравниваем насосы только по id.
    # "object" - аналог Object, isinstance - аналог instanceof.
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Pump):
            return NotImplemented
        return self._id == other._id

    # Аналог hashCode(). Если переопределён __eq__, нужен и __hash__.
    def __hash__(self) -> int:
        return hash(self._id)

    # Аналог toString(). Удобно при отладке и в сообщениях тестов.
    def __repr__(self) -> str:
        return f"Pump(id={self._id!r}, state={self._state.name})"
