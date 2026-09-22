"""Тесты сценария полива."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from plant_control.application.ports import PumpControlError, ValveControlError
from plant_control.application.watering_service import WateringService, WateringTimings
from plant_control.domain.collector import ValveState
from plant_control.domain.errors import MachineBusyError, PumpRuntimeExceededError
from plant_control.domain.machine import WateringMachine
from plant_control.domain.pump import PumpState
from tests.application.builders import collector_machine, simple_machine
from tests.application.fakes import (
    FakeClock,
    FakePumpControl,
    FakeSleeper,
    FakeValveControl,
    InMemoryMachineRepository,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TIMINGS = WateringTimings(valve_lead=timedelta(seconds=1), valve_lag=timedelta(seconds=2))


class Rig:
    """Сервис со всеми фейками и общим журналом команд."""

    def __init__(self, machine: WateringMachine) -> None:
        self.log: list[str] = []
        self.machine = machine
        self.clock = FakeClock(T0)
        self.sleeper = FakeSleeper(self.clock, self.log)
        self.pumps = FakePumpControl(self.log)
        self.valves = FakeValveControl(self.log)
        self.repo = InMemoryMachineRepository(machine)
        self.service = WateringService(
            self.repo, self.pumps, self.valves, self.clock, self.sleeper, TIMINGS
        )


# --- Успешный полив ---


async def test_simple_machine_runs_pump_for_planned_time() -> None:
    rig = Rig(simple_machine())

    plan = await rig.service.water("machine-1", "main", 100)

    # Насос 10 мл/с, доза 100 мл, трубка стекает в растение: 10 секунд.
    assert rig.log == ["pump on pump-1", "sleep 10s", "pump off pump-1"]
    assert plan.duration_s == pytest.approx(10)


async def test_collector_machine_opens_valve_before_pump_and_closes_after() -> None:
    rig = Rig(collector_machine())

    await rig.service.water("machine-1", "v2", 100)

    assert rig.log == [
        "open v2",
        "sleep 1s",
        "pump on pump-1",
        "sleep 10s",
        "pump off pump-1",
        "sleep 2s",
        "close v2",
    ]


async def test_successful_watering_draws_water_and_frees_machine() -> None:
    rig = Rig(simple_machine())

    await rig.service.water("machine-1", "main", 100)

    assert rig.machine.tank.volume_ml == pytest.approx(1900)
    assert rig.machine.pump.state is PumpState.OFF
    assert not rig.machine.is_busy


async def test_plan_does_not_touch_devices() -> None:
    rig = Rig(simple_machine())

    plan = await rig.service.plan("machine-1", "main", 100)

    assert plan.duration_s == pytest.approx(10)
    assert rig.log == []


# --- Правила домена ---


async def test_rules_violation_touches_nothing() -> None:
    rig = Rig(simple_machine())

    # 1000 мл при 10 мл/с - 100 секунд, насосу можно 60.
    with pytest.raises(PumpRuntimeExceededError):
        await rig.service.water("machine-1", "main", 1000)

    assert rig.log == []
    assert not rig.machine.is_busy


async def test_busy_machine_rejects_watering() -> None:
    rig = Rig(simple_machine())
    rig.machine.begin_watering(rig.machine.plan_watering("main", 100, T0))

    with pytest.raises(MachineBusyError):
        await rig.service.water("machine-1", "main", 100)

    assert rig.log == []


# --- Сбои ---


async def test_pump_failure_closes_valve_and_keeps_water() -> None:
    rig = Rig(collector_machine())
    rig.pumps.fail_on = True

    with pytest.raises(PumpControlError):
        await rig.service.water("machine-1", "v1", 100)

    collector = rig.machine.collector
    assert collector is not None
    assert collector.valve_state("v1") is ValveState.CLOSED
    # Насос мог включиться, а упал только ответ: сервис всё равно пытается выключить.
    assert "pump off pump-1" in rig.log
    assert rig.machine.tank.volume_ml == pytest.approx(2000)
    assert not rig.machine.is_busy


async def test_valve_open_failure_does_not_start_pump() -> None:
    rig = Rig(collector_machine())
    rig.valves.fail_open = True

    with pytest.raises(ValveControlError):
        await rig.service.water("machine-1", "v1", 100)

    assert not any(entry.startswith("pump on") for entry in rig.log)


async def test_pump_stop_failure_still_closes_valve_and_reports() -> None:
    rig = Rig(collector_machine())
    rig.pumps.fail_off = True

    with pytest.raises(PumpControlError):
        await rig.service.water("machine-1", "v1", 100)

    assert rig.log[-1] == "close v1"
    assert rig.machine.pump.state is PumpState.UNKNOWN


async def test_cancellation_during_pumping_stops_pump_and_closes_valve() -> None:
    rig = Rig(collector_machine())
    # Пауза 1 - после открытия клапана, пауза 2 - работа насоса. Отменяем на ней.
    rig.sleeper.cancel_on = 2

    with pytest.raises(asyncio.CancelledError):
        await rig.service.water("machine-1", "v1", 100)

    assert rig.log[-3:] == ["pump off pump-1", "sleep 2s", "close v1"]
    assert rig.machine.pump.state is PumpState.OFF
    assert not rig.machine.is_busy
    # Сколько воды пролилось, неизвестно: бак не списываем.
    assert rig.machine.tank.volume_ml == pytest.approx(2000)
