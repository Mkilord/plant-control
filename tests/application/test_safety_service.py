"""Тесты сервиса безопасности."""

from datetime import UTC, datetime, timedelta

from plant_control.application.safety_service import SafetyService
from plant_control.domain.collector import ValveState
from plant_control.domain.machine import WateringMachine
from plant_control.domain.pump import PumpState
from tests.application.builders import collector_machine, simple_machine
from tests.application.fakes import (
    FakeClock,
    FakePumpControl,
    FakeValveControl,
    InMemoryMachineRepository,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class Rig:
    def __init__(self, machine: WateringMachine) -> None:
        self.log: list[str] = []
        self.machine = machine
        self.clock = FakeClock(T0)
        self.pumps = FakePumpControl(self.log)
        self.valves = FakeValveControl(self.log)
        self.service = SafetyService(
            InMemoryMachineRepository(machine), self.pumps, self.valves, self.clock
        )


async def test_safe_start_sends_off_and_close_even_if_model_says_off() -> None:
    rig = Rig(collector_machine())

    errors = await rig.service.safe_start("machine-1")

    assert errors == []
    assert rig.log == ["pump off pump-1", "close v1", "close v2"]


async def test_safe_start_clears_unknown_states() -> None:
    rig = Rig(collector_machine())
    rig.machine.pump.mark_unknown()
    assert rig.machine.collector is not None
    rig.machine.collector.mark_unknown("v1")

    await rig.service.safe_start("machine-1")

    assert rig.machine.pump.state is PumpState.OFF
    assert rig.machine.collector.valve_state("v1") is ValveState.CLOSED


async def test_safe_start_reports_errors_but_tries_everything() -> None:
    rig = Rig(collector_machine())
    rig.pumps.fail_off = True

    errors = await rig.service.safe_start("machine-1")

    assert len(errors) == 1
    assert rig.log == ["close v1", "close v2"]


async def test_overrun_triggers_emergency_stop() -> None:
    rig = Rig(collector_machine())
    assert rig.machine.collector is not None
    rig.machine.collector.mark_opened("v1")
    rig.machine.pump.mark_started(T0)
    rig.clock.current = T0 + timedelta(seconds=61)

    stopped = await rig.service.check_overrun("machine-1")

    assert stopped
    assert rig.log == ["pump off pump-1", "close v1"]


async def test_no_overrun_does_nothing() -> None:
    rig = Rig(simple_machine())
    rig.machine.pump.mark_started(T0)
    rig.clock.current = T0 + timedelta(seconds=30)

    assert not await rig.service.check_overrun("machine-1")
    assert rig.log == []


async def test_observed_manual_start_updates_model() -> None:
    rig = Rig(simple_machine())

    await rig.service.observe_pump_state("machine-1", is_on=True)

    assert rig.machine.pump.state is PumpState.ON
    rig.clock.current = T0 + timedelta(seconds=61)
    assert await rig.service.check_overrun("machine-1")


async def test_observed_manual_stop_updates_model() -> None:
    rig = Rig(simple_machine())
    rig.machine.pump.mark_started(T0)

    await rig.service.observe_pump_state("machine-1", is_on=False)

    assert rig.machine.pump.state is PumpState.OFF
