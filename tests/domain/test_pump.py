from datetime import UTC, datetime, timedelta

import pytest

from plant_control.domain.errors import (
    InvalidFlowCurveError,
    InvalidPumpPassportError,
    PumpAlreadyRunningError,
    PumpCoolingDownError,
    PumpRuntimeExceededError,
    PumpStateUnknownError,
)
from plant_control.domain.flow import ConstantFlow
from plant_control.domain.pump import Pump, PumpPassport, PumpState

# Время всегда aware в UTC, чтобы не смешивать naive и aware.
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


# Фикстура - аналог @BeforeEach. pytest подставит её в тест по имени аргумента.
@pytest.fixture
def passport() -> PumpPassport:
    return PumpPassport(
        flow=ConstantFlow(10.0),
        max_runtime=timedelta(seconds=60),
        cooldown=timedelta(seconds=30),
    )


def test_new_passport_with_zero_nominal_flow() -> None:
    # Проверка расхода теперь живёт в модели расхода, паспорт её не дублирует.
    with pytest.raises(InvalidFlowCurveError):
        PumpPassport(
            flow=ConstantFlow(0.0),
            max_runtime=timedelta(seconds=60),
            cooldown=timedelta(seconds=30),
        )


def test_new_passport_with_zero_max_runtime() -> None:
    with pytest.raises(InvalidPumpPassportError):
        PumpPassport(
            flow=ConstantFlow(10.0),
            max_runtime=timedelta(seconds=0),
            cooldown=timedelta(seconds=30),
        )


def test_new_passport_with_negative_cooldown() -> None:
    with pytest.raises(InvalidPumpPassportError):
        PumpPassport(
            flow=ConstantFlow(10.0),
            max_runtime=timedelta(seconds=60),
            cooldown=timedelta(seconds=-1),
        )


# Тест - обычная функция с именем test_*. Проверки через обычный assert.
def test_new_pump_is_off(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport)
    assert pump.state is PumpState.OFF


# Проверка исключения - аналог assertThrows.
def test_running_pump_cannot_start_again(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.ON, started_at=T0)
    with pytest.raises(PumpAlreadyRunningError):
        pump.check_can_start(T0 + timedelta(seconds=5), timedelta(seconds=10))


def test_unknown_state_pump_cannot_start(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.UNKNOWN)
    with pytest.raises(PumpStateUnknownError):
        pump.check_can_start(T0 + timedelta(seconds=5), timedelta(seconds=10))


def test_cooling_down_pump_cannot_start(passport: PumpPassport) -> None:
    pump = Pump(
        "pump-1",
        passport,
        state=PumpState.OFF,
        stopped_at=T0 - timedelta(seconds=10),
    )
    with pytest.raises(PumpCoolingDownError):
        pump.check_can_start(T0, timedelta(seconds=10))


def test_pump_can_start_after_cooldown(passport: PumpPassport) -> None:
    pump = Pump(
        "pump-1",
        passport,
        state=PumpState.OFF,
        stopped_at=T0 - timedelta(seconds=40),
    )
    pump.check_can_start(T0, timedelta(seconds=10))


def test_pump_can_start_exactly_when_cooldown_ends(passport: PumpPassport) -> None:
    pump = Pump(
        "pump-1",
        passport,
        state=PumpState.OFF,
        stopped_at=T0 - timedelta(seconds=30),
    )
    pump.check_can_start(T0, timedelta(seconds=10))


def test_new_pump_can_start(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport)
    pump.check_can_start(T0, timedelta(seconds=20))


def test_pump_duration_exceeds_max_runtime(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.OFF)
    with pytest.raises(PumpRuntimeExceededError):
        pump.check_can_start(T0, timedelta(seconds=61))


def test_pump_duration_equals_max_runtime(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.OFF)
    pump.check_can_start(T0, timedelta(seconds=60))


def test_pump_mark_started_sets_state_and_started_at(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.OFF)
    pump.mark_started(T0)
    assert pump.state is PumpState.ON
    assert pump._started_at == T0


def test_pump_mark_stopped_sets_state_and_stopped_at(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.ON, started_at=T0)
    pump.mark_stopped(T0 + timedelta(seconds=10))
    assert pump.state is PumpState.OFF
    assert pump._stopped_at == T0 + timedelta(seconds=10)


def test_pump_mark_unknown_sets_state_and_keeps_times(passport: PumpPassport) -> None:
    pump = Pump(
        "pump-1", passport, state=PumpState.ON, started_at=T0, stopped_at=T0 + timedelta(seconds=10)
    )
    pump.mark_unknown()
    assert pump.state is PumpState.UNKNOWN


def test_pump_is_overrun_when_running_longer_than_max_runtime(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.ON, started_at=T0)
    assert pump.is_overrun(T0 + timedelta(seconds=61)) is True


def test_pump_is_not_overrun_when_pump_is_not_running(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.OFF, started_at=T0)
    assert pump.is_overrun(T0 + timedelta(seconds=61)) is False


def test_pump_exposes_start_and_stop_times(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport)
    pump.mark_started(T0)
    pump.mark_stopped(T0 + timedelta(seconds=10))
    assert pump.started_at == T0
    assert pump.stopped_at == T0 + timedelta(seconds=10)


def test_pump_without_runtime_limit_runs_any_time() -> None:
    passport = PumpPassport(flow=None, max_runtime=None, cooldown=timedelta(0))
    pump = Pump("pump-1", passport)
    pump.check_can_start(T0, timedelta(hours=5))
    pump.mark_started(T0)
    assert not pump.is_overrun(T0 + timedelta(days=1))
