"""Тесты формы бака и бака."""

import math

import pytest

from plant_control.domain.errors import (
    InvalidTankError,
    NotEnoughWaterError,
    TankOverflowError,
)
from plant_control.domain.tank import (
    HorizontalCylinder,
    MeasuredTank,
    RectangularTank,
    Tank,
    VerticalCylinder,
)

# --- Формы ---


def test_vertical_cylinder_capacity() -> None:
    geometry = VerticalCylinder(diameter_mm=200, height_mm=300)
    expected = math.pi * 100**2 * 300 / 1000
    assert geometry.capacity_ml() == pytest.approx(expected)


def test_vertical_cylinder_level_is_linear_in_volume() -> None:
    geometry = VerticalCylinder(diameter_mm=200, height_mm=300)
    half = geometry.capacity_ml() / 2
    assert geometry.level_at_volume(half) == pytest.approx(150)


def test_horizontal_cylinder_is_half_full_at_half_height() -> None:
    geometry = HorizontalCylinder(diameter_mm=250, length_mm=400)
    assert geometry.volume_at_level(125) == pytest.approx(geometry.capacity_ml() / 2)


def test_horizontal_cylinder_capacity() -> None:
    geometry = HorizontalCylinder(diameter_mm=250, length_mm=400)
    expected = math.pi * 125**2 * 400 / 1000
    assert geometry.capacity_ml() == pytest.approx(expected)


def test_horizontal_cylinder_level_is_not_linear() -> None:
    geometry = HorizontalCylinder(diameter_mm=250, length_mm=400)
    # Четверть объёма лежит ниже четверти высоты? Нет: у дна бочка узкая,
    # поэтому четверть объёма поднимает воду выше четверти высоты.
    assert geometry.level_at_volume(geometry.capacity_ml() / 4) > 250 / 4


@pytest.mark.parametrize("level", [0.0, 10.0, 62.5, 125.0, 200.0, 250.0])
def test_horizontal_cylinder_level_round_trip(level: float) -> None:
    # parametrize - один тест на несколько входов, как @ParameterizedTest в JUnit.
    geometry = HorizontalCylinder(diameter_mm=250, length_mm=400)
    volume = geometry.volume_at_level(level)
    assert geometry.level_at_volume(volume) == pytest.approx(level, abs=1e-6)


def test_rectangular_tank_capacity() -> None:
    geometry = RectangularTank(width_mm=200, depth_mm=100, height_mm=300)
    assert geometry.capacity_ml() == pytest.approx(6000)


def test_geometry_rejects_non_positive_size() -> None:
    with pytest.raises(InvalidTankError):
        VerticalCylinder(diameter_mm=0, height_mm=300)


# --- Бак ---


@pytest.fixture
def geometry() -> VerticalCylinder:
    # Площадь дна 10000 мм^2: 10 мл на каждый мм уровня, считать удобно.
    return VerticalCylinder(diameter_mm=2 * math.sqrt(10000 / math.pi), height_mm=300)


def test_tank_level_follows_volume(geometry: VerticalCylinder) -> None:
    tank = Tank(geometry, volume_ml=1500)
    assert tank.level_mm == pytest.approx(150)


def test_water_below_intake_is_unusable(geometry: VerticalCylinder) -> None:
    tank = Tank(geometry, volume_ml=1500, intake_height_mm=20)
    assert tank.unusable_volume_ml == pytest.approx(200)
    assert tank.usable_volume_ml == pytest.approx(1300)


def test_draw_reduces_volume(geometry: VerticalCylinder) -> None:
    tank = Tank(geometry, volume_ml=1500)
    tank.draw(500)
    assert tank.volume_ml == pytest.approx(1000)


def test_cannot_draw_water_below_intake(geometry: VerticalCylinder) -> None:
    tank = Tank(geometry, volume_ml=1500, intake_height_mm=20)
    with pytest.raises(NotEnoughWaterError):
        tank.draw(1400)


def test_fill_over_capacity_is_rejected(geometry: VerticalCylinder) -> None:
    tank = Tank(geometry, volume_ml=2900)
    with pytest.raises(TankOverflowError):
        tank.fill(200)


def test_tank_rejects_volume_over_capacity(geometry: VerticalCylinder) -> None:
    with pytest.raises(InvalidTankError):
        Tank(geometry, volume_ml=5000)


def test_tank_rejects_intake_above_tank(geometry: VerticalCylinder) -> None:
    with pytest.raises(InvalidTankError):
        Tank(geometry, volume_ml=1000, intake_height_mm=300)


def test_tank_with_reserve_sets_intake_from_volume(geometry: VerticalCylinder) -> None:
    tank = Tank.with_reserve(geometry, reserve_ml=500)
    assert tank.intake_height_mm == pytest.approx(50)
    assert tank.usable_volume_ml == pytest.approx(2500)


def test_set_measured_volume(geometry: VerticalCylinder) -> None:
    tank = Tank(geometry, volume_ml=1500)
    tank.set_measured_volume(700)
    assert tank.volume_ml == pytest.approx(700)


def test_measured_volume_over_capacity_is_rejected(geometry: VerticalCylinder) -> None:
    with pytest.raises(InvalidTankError):
        Tank(geometry, volume_ml=1500).set_measured_volume(5000)


# --- Бак по замеру ---


def test_measured_tank_capacity_is_measured_volume() -> None:
    assert MeasuredTank(volume_ml=1800, height_mm=150).capacity_ml() == 1800


def test_measured_tank_level_is_proportional_to_volume() -> None:
    geometry = MeasuredTank(volume_ml=1800, height_mm=150)
    assert geometry.level_at_volume(600) == pytest.approx(50)
    assert geometry.volume_at_level(100) == pytest.approx(1200)


def test_measured_tank_reserve_in_ml() -> None:
    tank = Tank.with_reserve(MeasuredTank(volume_ml=2000, height_mm=160), reserve_ml=500)
    assert tank.usable_volume_ml == pytest.approx(1500)
    assert tank.intake_height_mm == pytest.approx(40)


def test_measured_tank_rejects_zero() -> None:
    with pytest.raises(InvalidTankError):
        MeasuredTank(volume_ml=0, height_mm=150)
