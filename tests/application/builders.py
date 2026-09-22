"""Готовые машины для тестов сервисов."""

import math
from datetime import timedelta

from plant_control.domain.collector import Collector, Valve
from plant_control.domain.connection import Connection, Outlet, Route
from plant_control.domain.flow import ConstantFlow
from plant_control.domain.machine import WateringMachine
from plant_control.domain.pump import Pump, PumpPassport
from plant_control.domain.tank import Tank, VerticalCylinder
from plant_control.domain.watering import CollectorPlumbing, DirectPlumbing, StartLevelHead

# Бак 2 л, 10 мл на мм, 500 мл запаса. Насос 10 мл/с, трубки по 10 мл.
GEOMETRY = VerticalCylinder(diameter_mm=2 * math.sqrt(10000 / math.pi), height_mm=200)
TUBE_10ML = Connection(length_mm=10000 / math.pi, inner_radius_mm=1)
ROUTE = Route(connection=TUBE_10ML, outlet=Outlet(height_above_tank_bottom_mm=300))


def make_pump() -> Pump:
    passport = PumpPassport(
        flow=ConstantFlow(10.0),
        max_runtime=timedelta(seconds=60),
        cooldown=timedelta(seconds=30),
    )
    return Pump("pump-1", passport)


def simple_machine() -> WateringMachine:
    """Без коллектора, вся вода из трубки стекает в растение: прокачка равна дозе."""
    return WateringMachine(
        "machine-1",
        pump=make_pump(),
        tank=Tank.with_reserve(GEOMETRY, reserve_ml=500),
        head_model=StartLevelHead(),
        plumbing=DirectPlumbing(back_to_tank_fraction=0.0),
        routes={"main": ROUTE},
    )


def collector_machine() -> WateringMachine:
    """С коллектором на два клапана, трубка до коллектора уже полная."""
    return WateringMachine(
        "machine-1",
        pump=make_pump(),
        tank=Tank.with_reserve(GEOMETRY, reserve_ml=500),
        head_model=StartLevelHead(),
        plumbing=CollectorPlumbing(supply=TUBE_10ML),
        routes={"v1": ROUTE, "v2": ROUTE},
        collector=Collector("collector-1", [Valve("v1"), Valve("v2")]),
        supply_is_filled=True,
    )
