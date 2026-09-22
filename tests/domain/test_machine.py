"""Тесты поливальной машины."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from plant_control.domain.collector import Collector, Valve
from plant_control.domain.connection import Connection, Outlet, Route
from plant_control.domain.errors import (
    AnotherValveOpenError,
    InvalidMachineError,
    MachineBusyError,
    NotEnoughWaterError,
    PumpAlreadyRunningError,
    PumpRuntimeExceededError,
    UnknownRouteError,
    UnknownValveError,
)
from plant_control.domain.flow import LinearFlow
from plant_control.domain.machine import WateringMachine
from plant_control.domain.pump import Pump, PumpPassport, PumpState
from plant_control.domain.tank import Tank, VerticalCylinder
from plant_control.domain.watering import CollectorPlumbing, DirectPlumbing, MidDoseHead

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

# Бак 2 л, 10 мл на мм уровня, нижние 500 мл недоступны насосу.
GEOMETRY = VerticalCylinder(diameter_mm=2 * math.sqrt(10000 / math.pi), height_mm=200)
TUBE_10ML = Connection(length_mm=10000 / math.pi, inner_radius_mm=1)
ROUTE = Route(connection=TUBE_10ML, outlet=Outlet(height_above_tank_bottom_mm=300))
FLOW = LinearFlow(max_flow_ml_s=6, max_head_mm=1200)


@pytest.fixture
def pump() -> Pump:
    passport = PumpPassport(
        flow=FLOW, max_runtime=timedelta(seconds=60), cooldown=timedelta(seconds=30)
    )
    return Pump("pump-1", passport)


def tank() -> Tank:
    return Tank.with_reserve(GEOMETRY, reserve_ml=500)


def simple_machine(pump: Pump, fraction: float = 0.5) -> WateringMachine:
    return WateringMachine(
        "machine-1",
        pump=pump,
        tank=tank(),
        head_model=MidDoseHead(),
        plumbing=DirectPlumbing(back_to_tank_fraction=fraction),
        routes={"main": ROUTE},
    )


def collector_machine(pump: Pump) -> WateringMachine:
    collector = Collector("collector-1", [Valve("v1"), Valve("v2")])
    return WateringMachine(
        "machine-1",
        pump=pump,
        tank=tank(),
        head_model=MidDoseHead(),
        plumbing=CollectorPlumbing(supply=TUBE_10ML),
        routes={"v1": ROUTE, "v2": ROUTE},
        collector=collector,
    )


# --- Машина без коллектора ---


def test_simple_machine_plans_watering(pump: Pump) -> None:
    plan = simple_machine(pump, fraction=0.5).plan_watering("main", 100, T0)
    assert plan.pumped_ml == pytest.approx(105)
    assert plan.consumed_ml == pytest.approx(100)
    assert plan.duration_s > 0


def test_complete_watering_draws_consumed_volume(pump: Pump) -> None:
    machine = simple_machine(pump)
    plan = machine.plan_watering("main", 100, T0)
    machine.complete_watering(plan)
    assert machine.tank.volume_ml == pytest.approx(1900)


def test_planning_does_not_change_tank(pump: Pump) -> None:
    machine = simple_machine(pump)
    machine.plan_watering("main", 100, T0)
    assert machine.tank.volume_ml == pytest.approx(2000)


def test_unknown_route(pump: Pump) -> None:
    with pytest.raises(UnknownRouteError):
        simple_machine(pump).plan_watering("nope", 100, T0)


def test_machine_does_not_plan_while_pump_is_running(pump: Pump) -> None:
    pump.mark_started(T0)
    with pytest.raises(PumpAlreadyRunningError):
        simple_machine(pump).plan_watering("main", 100, T0 + timedelta(seconds=5))


def test_dose_longer_than_pump_max_runtime_is_rejected(pump: Pump) -> None:
    # 1000 мл при расходе около 5 мл/с - больше 3 минут, а насосу можно 60 секунд.
    with pytest.raises(PumpRuntimeExceededError):
        simple_machine(pump).plan_watering("main", 1000, T0)


def test_water_below_reserve_is_not_used(pump: Pump) -> None:
    with pytest.raises(NotEnoughWaterError):
        simple_machine(pump).plan_watering("main", 1600, T0)


def test_machine_without_collector_must_have_one_route(pump: Pump) -> None:
    with pytest.raises(InvalidMachineError):
        WateringMachine(
            "m",
            pump=pump,
            tank=tank(),
            head_model=MidDoseHead(),
            plumbing=DirectPlumbing(),
            routes={"a": ROUTE, "b": ROUTE},
        )


def test_collector_plumbing_requires_collector(pump: Pump) -> None:
    with pytest.raises(InvalidMachineError):
        WateringMachine(
            "m",
            pump=pump,
            tank=tank(),
            head_model=MidDoseHead(),
            plumbing=CollectorPlumbing(supply=TUBE_10ML),
            routes={"main": ROUTE},
        )


def test_direct_plumbing_does_not_accept_collector(pump: Pump) -> None:
    collector = Collector("c", [Valve("v1"), Valve("v2")])
    with pytest.raises(InvalidMachineError):
        WateringMachine(
            "m",
            pump=pump,
            tank=tank(),
            head_model=MidDoseHead(),
            plumbing=DirectPlumbing(),
            routes={"v1": ROUTE},
            collector=collector,
        )


# --- Машина с коллектором ---


def test_first_watering_primes_supply_tube(pump: Pump) -> None:
    plan = collector_machine(pump).plan_watering("v1", 100, T0)
    assert plan.pumped_ml == pytest.approx(110)


def test_after_first_watering_supply_tube_stays_filled(pump: Pump) -> None:
    machine = collector_machine(pump)
    machine.complete_watering(machine.plan_watering("v1", 100, T0))
    plan = machine.plan_watering("v2", 100, T0)
    assert machine.supply_is_filled
    assert plan.pumped_ml == pytest.approx(100)


def test_route_must_match_collector_valve(pump: Pump) -> None:
    collector = Collector("c", [Valve("v1"), Valve("v2")])
    with pytest.raises(UnknownValveError):
        WateringMachine(
            "m",
            pump=pump,
            tank=tank(),
            head_model=MidDoseHead(),
            plumbing=CollectorPlumbing(supply=TUBE_10ML),
            routes={"v3": ROUTE},
            collector=collector,
        )


def test_pump_state_is_untouched_by_planning(pump: Pump) -> None:
    simple_machine(pump).plan_watering("main", 100, T0)
    assert pump.state is PumpState.OFF


# --- Один полив за раз ---


def test_machine_rejects_second_watering_while_busy(pump: Pump) -> None:
    machine = simple_machine(pump)
    machine.begin_watering(machine.plan_watering("main", 100, T0))
    assert machine.is_busy
    with pytest.raises(MachineBusyError):
        machine.plan_watering("main", 100, T0)


def test_complete_watering_frees_machine(pump: Pump) -> None:
    machine = simple_machine(pump)
    plan = machine.plan_watering("main", 100, T0)
    machine.begin_watering(plan)
    machine.complete_watering(plan)
    assert not machine.is_busy


def test_abort_watering_frees_machine_and_keeps_water(pump: Pump) -> None:
    machine = simple_machine(pump)
    machine.begin_watering(machine.plan_watering("main", 100, T0))
    machine.abort_watering()
    assert not machine.is_busy
    assert machine.tank.volume_ml == pytest.approx(2000)


def test_valve_for_route(pump: Pump) -> None:
    assert simple_machine(pump).valve_for("main") is None
    assert collector_machine(pump).valve_for("v2") == "v2"


def test_machine_does_not_plan_when_valve_is_open(pump: Pump) -> None:
    machine = collector_machine(pump)
    assert machine.collector is not None
    machine.collector.mark_opened("v1")
    with pytest.raises(AnotherValveOpenError):
        machine.plan_watering("v2", 100, T0)
