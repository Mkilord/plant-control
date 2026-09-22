"""Тесты сервиса управления насосом."""

from datetime import UTC, datetime, timedelta

import pytest

from plant_control.application.ports import PumpControlError
from plant_control.application.pump_service import PumpService
from plant_control.domain.errors import PumpAlreadyRunningError
from plant_control.domain.flow import ConstantFlow
from plant_control.domain.pump import Pump, PumpPassport, PumpState

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


# --- Фейковые реализации портов ---
# Они не наследуют протоколы: mypy проверит совпадение методов сам.


class FakeClock:
    """Часы, время на которых задаёт тест."""

    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class FakePumpControl:
    """Записывает команды вместо реального реле. Может изображать сбой."""

    def __init__(self) -> None:
        # list[str] - аналог List<String>
        self.commands: list[str] = []
        self.fail = False

    async def turn_on(self, pump_id: str) -> None:
        if self.fail:
            raise PumpControlError("relay unavailable")
        self.commands.append(f"on:{pump_id}")

    async def turn_off(self, pump_id: str) -> None:
        if self.fail:
            raise PumpControlError("relay unavailable")
        self.commands.append(f"off:{pump_id}")


class InMemoryPumpRepository:
    """Хранит насосы в словаре, как HashMap."""

    def __init__(self, *pumps: Pump) -> None:
        # *pumps - произвольное число аргументов (как Pump... pumps в Java)
        self.pumps: dict[str, Pump] = {p.id: p for p in pumps}

    async def get(self, pump_id: str) -> Pump:
        return self.pumps[pump_id]

    async def save(self, pump: Pump) -> None:
        self.pumps[pump.id] = pump


# --- Фикстуры ---


@pytest.fixture
def passport() -> PumpPassport:
    return PumpPassport(
        flow=ConstantFlow(10.0),
        max_runtime=timedelta(seconds=60),
        cooldown=timedelta(seconds=30),
    )


# --- Тесты ---
# Асинхронный тест: async def плюс await внутри.
# Запускать его будет плагин pytest-asyncio (см. pyproject.toml).


async def test_start_turns_relay_on_and_marks_pump_on(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport)
    control = FakePumpControl()
    service = PumpService(control, InMemoryPumpRepository(pump), FakeClock(T0))

    await service.start("pump-1", timedelta(seconds=10))

    assert control.commands == ["on:pump-1"]
    assert pump.state is PumpState.ON


async def test_start_does_not_touch_relay_when_rules_fail(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.ON, started_at=T0)
    control = FakePumpControl()
    service = PumpService(control, InMemoryPumpRepository(pump), FakeClock(T0))

    with pytest.raises(PumpAlreadyRunningError):
        await service.start("pump-1", timedelta(seconds=10))

    assert control.commands == []


async def test_start_marks_pump_unknown_when_relay_fails(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport)
    control = FakePumpControl()
    control.fail = True
    service = PumpService(control, InMemoryPumpRepository(pump), FakeClock(T0))

    with pytest.raises(PumpControlError):
        await service.start("pump-1", timedelta(seconds=10))

    assert pump.state is PumpState.UNKNOWN


async def test_stop_turns_relay_off_and_marks_pump_off(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.ON, started_at=T0)
    control = FakePumpControl()
    service = PumpService(control, InMemoryPumpRepository(pump), FakeClock(T0))

    await service.stop("pump-1")

    assert control.commands == ["off:pump-1"]
    assert pump.state is PumpState.OFF


async def test_stop_marks_pump_unknown_when_relay_fails(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.ON, started_at=T0)
    control = FakePumpControl()
    control.fail = True
    service = PumpService(control, InMemoryPumpRepository(pump), FakeClock(T0))

    with pytest.raises(PumpControlError):
        await service.stop("pump-1")

    assert pump.state is PumpState.UNKNOWN


async def test_stop_works_from_unknown_state(passport: PumpPassport) -> None:
    pump = Pump("pump-1", passport, state=PumpState.UNKNOWN)
    control = FakePumpControl()
    service = PumpService(control, InMemoryPumpRepository(pump), FakeClock(T0))

    await service.stop("pump-1")

    assert control.commands == ["off:pump-1"]
    assert pump.state is PumpState.OFF
