"""Тесты расчёта полива."""

import math

import pytest

from plant_control.domain.connection import Connection, Outlet, Route
from plant_control.domain.errors import (
    InvalidWateringRequestError,
    NotEnoughWaterError,
    PumpCannotDeliverError,
)
from plant_control.domain.flow import ConstantFlow, LinearFlow
from plant_control.domain.tank import Tank, VerticalCylinder
from plant_control.domain.watering import (
    CollectorPlumbing,
    DirectPlumbing,
    HeadModel,
    MidDoseHead,
    StartLevelHead,
    StepwiseHead,
    calculate_watering,
)

# Бак с площадью дна 10000 мм^2: 10 мл на мм уровня. 3000 мл при полном.
GEOMETRY = VerticalCylinder(diameter_mm=2 * math.sqrt(10000 / math.pi), height_mm=300)
# Трубка с объёмом ровно 10 мл.
TUBE_10ML = Connection(length_mm=10000 / math.pi, inner_radius_mm=1)
ROUTE = Route(connection=TUBE_10ML, outlet=Outlet(height_above_tank_bottom_mm=500))
LINEAR = LinearFlow(max_flow_ml_s=6, max_head_mm=1200)
ALL_BACK = DirectPlumbing(back_to_tank_fraction=1.0)


def full_tank() -> Tank:
    return Tank(GEOMETRY, volume_ml=GEOMETRY.capacity_ml())


def test_connection_dead_volume() -> None:
    assert TUBE_10ML.dead_volume_ml == pytest.approx(10)


# --- Обвязка без коллектора ---


@pytest.mark.parametrize(("fraction", "pumped"), [(0.0, 100.0), (0.5, 105.0), (1.0, 110.0)])
def test_direct_plumbing_pumps_dose_plus_part_that_flows_back(
    fraction: float, pumped: float
) -> None:
    plan = calculate_watering(
        tank=full_tank(),
        flow=ConstantFlow(5),
        route=ROUTE,
        dose_ml=100,
        plumbing=DirectPlumbing(back_to_tank_fraction=fraction),
        head_model=StartLevelHead(),
    )
    assert plan.pumped_ml == pytest.approx(pumped)
    # Бак в итоге теряет только дозу: остальное стекает обратно.
    assert plan.consumed_ml == pytest.approx(100)


def test_direct_plumbing_rejects_fraction_outside_range() -> None:
    with pytest.raises(InvalidWateringRequestError):
        DirectPlumbing(back_to_tank_fraction=1.5)


# --- Обвязка с коллектором ---


def test_collector_plumbing_primes_empty_supply_tube() -> None:
    plan = calculate_watering(
        tank=full_tank(),
        flow=ConstantFlow(5),
        route=ROUTE,
        dose_ml=100,
        plumbing=CollectorPlumbing(supply=TUBE_10ML),
        head_model=StartLevelHead(),
        supply_is_filled=False,
    )
    assert plan.pumped_ml == pytest.approx(110)
    # Вода в трубке до коллектора остаётся там: бак её теряет.
    assert plan.consumed_ml == pytest.approx(110)


def test_collector_plumbing_has_no_extra_when_supply_is_filled() -> None:
    plan = calculate_watering(
        tank=full_tank(),
        flow=ConstantFlow(5),
        route=ROUTE,
        dose_ml=100,
        plumbing=CollectorPlumbing(supply=TUBE_10ML),
        head_model=StartLevelHead(),
        supply_is_filled=True,
    )
    assert plan.pumped_ml == pytest.approx(100)
    assert plan.consumed_ml == pytest.approx(100)


# --- Время ---


def test_constant_flow_duration_is_volume_over_flow() -> None:
    plan = calculate_watering(
        tank=full_tank(),
        flow=ConstantFlow(5),
        route=ROUTE,
        dose_ml=90,
        plumbing=ALL_BACK,
        head_model=StartLevelHead(),
    )
    assert plan.duration_s == pytest.approx(100 / 5)


def test_linear_flow_uses_head_at_start_level() -> None:
    # Полный бак: уровень 300, напор 500 - 300 = 200, расход 6 * (1 - 200/1200) = 5.
    plan = calculate_watering(
        tank=full_tank(),
        flow=LINEAR,
        route=ROUTE,
        dose_ml=90,
        plumbing=ALL_BACK,
        head_model=StartLevelHead(),
    )
    assert plan.head_start_mm == pytest.approx(200)
    assert plan.flow_start_ml_s == pytest.approx(5)
    assert plan.duration_s == pytest.approx(100 / 5)


def test_emptier_tank_needs_more_time_for_same_dose() -> None:
    def duration(volume: float) -> float:
        return calculate_watering(
            tank=Tank(GEOMETRY, volume_ml=volume),
            flow=LINEAR,
            route=ROUTE,
            dose_ml=100,
            plumbing=ALL_BACK,
            head_model=StartLevelHead(),
        ).duration_s

    assert duration(500) > duration(3000)


def test_head_models_are_ordered_by_level_they_use() -> None:
    def duration(model: HeadModel) -> float:
        return calculate_watering(
            tank=full_tank(),
            flow=LINEAR,
            route=ROUTE,
            dose_ml=990,
            plumbing=ALL_BACK,
            head_model=model,
        ).duration_s

    start = duration(StartLevelHead())
    mid = duration(MidDoseHead())
    stepwise = duration(StepwiseHead(steps=100))
    assert start < stepwise
    assert mid == pytest.approx(stepwise, rel=0.01)


def test_route_correction_scales_duration() -> None:
    slow_route = Route(connection=TUBE_10ML, outlet=ROUTE.outlet, correction=0.5)

    def duration(route: Route) -> float:
        return calculate_watering(
            tank=full_tank(),
            flow=ConstantFlow(5),
            route=route,
            dose_ml=90,
            plumbing=ALL_BACK,
            head_model=StartLevelHead(),
        ).duration_s

    assert duration(slow_route) == pytest.approx(2 * duration(ROUTE))


# --- Ошибки и чистота ---


def test_not_enough_water() -> None:
    with pytest.raises(NotEnoughWaterError):
        calculate_watering(
            tank=Tank(GEOMETRY, volume_ml=50),
            flow=LINEAR,
            route=ROUTE,
            dose_ml=100,
            plumbing=ALL_BACK,
            head_model=StartLevelHead(),
        )


def test_pump_cannot_lift_to_outlet() -> None:
    high = Route(connection=TUBE_10ML, outlet=Outlet(height_above_tank_bottom_mm=2000))
    with pytest.raises(PumpCannotDeliverError):
        calculate_watering(
            tank=full_tank(),
            flow=LINEAR,
            route=high,
            dose_ml=100,
            plumbing=ALL_BACK,
            head_model=StartLevelHead(),
        )


def test_calculation_does_not_change_tank() -> None:
    tank = full_tank()
    before = tank.volume_ml
    calculate_watering(
        tank=tank,
        flow=LINEAR,
        route=ROUTE,
        dose_ml=100,
        plumbing=ALL_BACK,
        head_model=StartLevelHead(),
    )
    assert tank.volume_ml == before


def test_non_positive_dose_is_rejected() -> None:
    with pytest.raises(InvalidWateringRequestError):
        calculate_watering(
            tank=full_tank(),
            flow=LINEAR,
            route=ROUTE,
            dose_ml=0,
            plumbing=ALL_BACK,
            head_model=StartLevelHead(),
        )
