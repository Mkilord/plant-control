"""Тесты калибровки: обработка замеров, профиль, полив по профилю, автоподстройка."""

import math
from datetime import UTC, datetime

import pytest

from plant_control.domain.calibration import (
    CalibrationWarning,
    FlowPoint,
    FlowProfile,
    combine_runs,
    evaluate_marks_run,
    evaluate_timed_runs,
    fit_line,
    profile_from,
)
from plant_control.domain.connection import Connection
from plant_control.domain.errors import (
    CalibrationError,
    DoseTooSmallError,
    NotEnoughWaterError,
    PumpCannotDeliverError,
)
from plant_control.domain.tank import Tank, VerticalCylinder
from plant_control.domain.tuning import FlowTracker, TuningThresholds
from plant_control.domain.watering import (
    CollectorPlumbing,
    DirectPlumbing,
    calculate_calibrated_watering,
)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
# 10 мл на мм уровня, 3000 мл при полном.
GEOMETRY = VerticalCylinder(diameter_mm=2 * math.sqrt(10000 / math.pi), height_mm=300)
TUBE_10ML = Connection(length_mm=10000 / math.pi, inner_radius_mm=1)


def full_tank() -> Tank:
    return Tank(GEOMETRY, volume_ml=GEOMETRY.capacity_ml())


# --- Прямая ---


def test_fit_line_exact() -> None:
    fit = fit_line([(0, 1), (1, 3), (2, 5)])
    assert fit.slope == pytest.approx(2)
    assert fit.intercept == pytest.approx(1)
    assert fit.rms == pytest.approx(0)


def test_fit_line_needs_distinct_times() -> None:
    with pytest.raises(CalibrationError):
        fit_line([(1, 1), (1, 2)])


# --- Прогон по меткам ---


def test_marks_run_gives_flow_prime_and_afterflow() -> None:
    # 10 мл/с, вода пошла через 3 с: метки 500/1000/1500 на 53/103/153 с.
    result = evaluate_marks_run([(53, 500), (103, 1000), (153, 1500)], final_volume_ml=1530)
    assert result.flow_ml_s == pytest.approx(10)
    assert result.prime_s == pytest.approx(3)
    assert result.afterflow_ml == pytest.approx(30)
    assert result.spread_pct == pytest.approx(0)
    assert result.warnings == ()


def test_marks_run_with_water_started_point() -> None:
    result = evaluate_marks_run([(53, 500)], final_volume_ml=510, water_started_s=3)
    assert result.flow_ml_s == pytest.approx(10)
    assert result.prime_s == pytest.approx(3)
    # Две точки: разброс посчитать нельзя.
    assert result.spread_pct is None


def test_one_mark_without_water_started_is_not_enough() -> None:
    with pytest.raises(CalibrationError):
        evaluate_marks_run([(53, 500)], final_volume_ml=510)


def test_marks_must_increase() -> None:
    with pytest.raises(CalibrationError):
        evaluate_marks_run([(53, 500), (50, 1000)], final_volume_ml=1000)
    with pytest.raises(CalibrationError):
        evaluate_marks_run([(53, 1000), (60, 500)], final_volume_ml=1000)


def test_final_volume_below_last_mark_is_an_error() -> None:
    with pytest.raises(CalibrationError):
        evaluate_marks_run([(10, 500), (20, 1000)], final_volume_ml=900)


def test_short_run_warns() -> None:
    result = evaluate_marks_run([(5, 500), (10, 1000)], final_volume_ml=1000)
    assert CalibrationWarning.TOO_FAST in result.warnings


def test_dropping_flow_warns() -> None:
    # Каждые 500 мл идут всё дольше: 50, 60, 75 с.
    result = evaluate_marks_run([(50, 500), (110, 1000), (185, 1500)], final_volume_ml=1500)
    assert CalibrationWarning.FLOW_DROPS in result.warnings


def test_scattered_marks_warn() -> None:
    result = evaluate_marks_run(
        [(20, 500), (80, 1000), (90, 1500), (200, 2000)], final_volume_ml=2000
    )
    assert CalibrationWarning.HIGH_SPREAD in result.warnings


# --- Прогоны по времени ---


def test_timed_runs_give_flow_and_prime() -> None:
    # 10 мл/с, 2 с ничего не доходит.
    result = evaluate_timed_runs([(10, 80), (30, 280)])
    assert result.flow_ml_s == pytest.approx(10)
    assert result.prime_s == pytest.approx(2)
    assert result.afterflow_ml == 0
    assert CalibrationWarning.TOO_FAST not in result.warnings


def test_single_duration_gives_average_flow_without_prime() -> None:
    result = evaluate_timed_runs([(30, 300), (30, 330)])
    assert result.flow_ml_s == pytest.approx(10.5)
    assert result.prime_s == 0
    assert CalibrationWarning.NO_PRIME in result.warnings


def test_timed_runs_reject_zero_volume() -> None:
    with pytest.raises(CalibrationError):
        evaluate_timed_runs([(10, 0), (20, 100)])


# --- Несколько прогонов ---


def test_combine_runs_averages() -> None:
    a = evaluate_marks_run([(53, 500), (103, 1000)], final_volume_ml=1020)
    b = evaluate_marks_run([(51, 500), (101, 1000)], final_volume_ml=1040)
    combined = combine_runs([a, b])
    assert combined.flow_ml_s == pytest.approx(10)
    assert combined.prime_s == pytest.approx(2)
    assert combined.afterflow_ml == pytest.approx(30)
    assert combined.spread_pct == pytest.approx(0)


# --- Профиль ---


def test_profile_flow_by_level() -> None:
    profile = FlowProfile(points=(FlowPoint(3000, 10), FlowPoint(1000, 8)))
    assert profile.flow_at(2000) == pytest.approx(9)
    # За пределами точек - продолжение прямой.
    assert profile.flow_at(0) == pytest.approx(7)


def test_profile_extrapolation_cannot_go_to_zero() -> None:
    profile = FlowProfile(points=(FlowPoint(3000, 10), FlowPoint(2000, 2)))
    with pytest.raises(PumpCannotDeliverError):
        profile.flow_at(0)


def test_profile_needs_distinct_levels() -> None:
    with pytest.raises(CalibrationError):
        FlowProfile(points=(FlowPoint(1000, 10), FlowPoint(1000, 8)))


def test_inherited_profile_shifts_prime_and_afterflow_by_tube() -> None:
    base = FlowProfile(points=(FlowPoint(3000, 10),), prime_s=2, afterflow_ml=20)
    longer = base.inherited(tube_delta_ml=30)
    assert longer.reference_flow_ml_s == 10
    assert longer.prime_s == pytest.approx(5)
    assert longer.afterflow_ml == pytest.approx(50)
    shorter = base.inherited(tube_delta_ml=-100)
    assert shorter.prime_s == 0
    assert shorter.afterflow_ml == 0


def test_profile_from_result() -> None:
    result = evaluate_timed_runs([(10, 80), (30, 280)])
    profile = profile_from(result, tank_volume_ml=2500)
    assert len(profile.points) == 1
    assert profile.points[0].tank_volume_ml == 2500
    assert profile.points[0].flow_ml_s == pytest.approx(10)


# --- Полив по профилю ---


def test_calibrated_watering_duration() -> None:
    profile = FlowProfile(points=(FlowPoint(3000, 10),), prime_s=3, afterflow_ml=30)
    plan = calculate_calibrated_watering(
        tank=full_tank(), profile=profile, dose_ml=530, plumbing=DirectPlumbing()
    )
    # 3 с задержки плюс 500 мл по 10 мл/с.
    assert plan.duration_s == pytest.approx(53)
    assert plan.consumed_ml == pytest.approx(530)
    assert plan.pumped_ml == pytest.approx(30 + 500)


def test_calibrated_watering_matches_the_calibration_run() -> None:
    # Что намерили, то и должны получить: прогон 153 с дал 1530 мл.
    result = evaluate_marks_run([(53, 500), (103, 1000), (153, 1500)], final_volume_ml=1530)
    profile = profile_from(result, tank_volume_ml=3000)
    plan = calculate_calibrated_watering(
        tank=full_tank(), profile=profile, dose_ml=1530, plumbing=DirectPlumbing()
    )
    assert plan.duration_s == pytest.approx(153)


def test_empty_supply_adds_time_and_water() -> None:
    profile = FlowProfile(points=(FlowPoint(3000, 10),))
    plumbing = CollectorPlumbing(supply=TUBE_10ML)
    filled = calculate_calibrated_watering(
        tank=full_tank(), profile=profile, dose_ml=100, plumbing=plumbing, supply_is_filled=True
    )
    empty = calculate_calibrated_watering(
        tank=full_tank(), profile=profile, dose_ml=100, plumbing=plumbing, supply_is_filled=False
    )
    assert empty.duration_s - filled.duration_s == pytest.approx(1)
    assert empty.consumed_ml - filled.consumed_ml == pytest.approx(10)


def test_dose_below_afterflow_is_rejected() -> None:
    profile = FlowProfile(points=(FlowPoint(3000, 10),), afterflow_ml=50)
    with pytest.raises(DoseTooSmallError):
        calculate_calibrated_watering(
            tank=full_tank(), profile=profile, dose_ml=40, plumbing=DirectPlumbing()
        )


def test_calibrated_watering_checks_water() -> None:
    profile = FlowProfile(points=(FlowPoint(3000, 10),))
    tank = Tank(GEOMETRY, volume_ml=100)
    with pytest.raises(NotEnoughWaterError):
        calculate_calibrated_watering(
            tank=tank, profile=profile, dose_ml=200, plumbing=DirectPlumbing()
        )


def test_level_dependent_profile_takes_flow_at_mid_dose() -> None:
    profile = FlowProfile(points=(FlowPoint(3000, 10), FlowPoint(1000, 8)))
    plan = calculate_calibrated_watering(
        tank=full_tank(), profile=profile, dose_ml=2000, plumbing=DirectPlumbing()
    )
    # Середина полива при 2000 мл в баке: 9 мл/с.
    assert plan.duration_s == pytest.approx(2000 / 9)
    assert plan.flow_start_ml_s == pytest.approx(10)
    assert plan.flow_end_ml_s == pytest.approx(8)


# --- Автоподстройка ---


def test_tracker_suggests_factor() -> None:
    tracker = FlowTracker()
    for _ in range(3):
        tracker = tracker.with_watering(100, calibrated=True)
    # По расчёту в баке 700, на деле 640: ушло 360 вместо 300.
    suggestion = tracker.evaluate(700, 640, NOW)
    assert suggestion is not None
    assert suggestion.factor == pytest.approx(1.2)
    assert suggestion.actual_ml == pytest.approx(360)


def test_tracker_ignores_small_deviation_and_few_waterings() -> None:
    tracker = FlowTracker().with_watering(100, True).with_watering(100, True)
    assert tracker.evaluate(800, 700, NOW) is None
    tracker = tracker.with_watering(100, True)
    assert tracker.evaluate(700, 690, NOW) is None
    assert tracker.evaluate(700, 690, NOW, TuningThresholds(deviation_pct=1)) is not None


def test_tracker_invalid_after_passport_watering() -> None:
    tracker = FlowTracker()
    for _ in range(3):
        tracker = tracker.with_watering(100, calibrated=True)
    tracker = tracker.with_watering(100, calibrated=False)
    assert tracker.evaluate(700, 500, NOW) is None


def test_tracker_skips_unrecorded_refill() -> None:
    tracker = FlowTracker()
    for _ in range(3):
        tracker = tracker.with_watering(100, calibrated=True)
    # Воды больше, чем могло быть: долили без записи.
    assert tracker.evaluate(700, 1100, NOW) is None
