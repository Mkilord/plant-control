from datetime import UTC, datetime, timedelta

import pytest

from plant_control.domain.errors import InvalidPumpPassportError, PumpAlreadyRunningError
from plant_control.domain.pump import Pump, PumpPassport, PumpState

# Время всегда aware в UTC, чтобы не смешивать naive и aware.
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


# Фикстура - аналог @BeforeEach. pytest подставит её в тест по имени аргумента.
@pytest.fixture
def passport() -> PumpPassport:
    return PumpPassport(
        nominal_flow_ml_s=10.0,
        max_runtime=timedelta(seconds=60),
        cooldown=timedelta(seconds=30),
    )

def test_new_passport_with_zero_nominal_flow() -> None:
    with pytest.raises(InvalidPumpPassportError):
        PumpPassport(
            nominal_flow_ml_s=0.0,
            max_runtime=timedelta(seconds=60),
            cooldown=timedelta(seconds=30),
        )

def test_new_passport_with_zero_max_runtime() -> None:
    with pytest.raises(InvalidPumpPassportError):
        PumpPassport(
            nominal_flow_ml_s=10.0,
            max_runtime=timedelta(seconds=0),
            cooldown=timedelta(seconds=30),
        )

def test_new_passport_with_negative_cooldown() -> None:
    with pytest.raises(InvalidPumpPassportError):
        PumpPassport(
            nominal_flow_ml_s=10.0,
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
