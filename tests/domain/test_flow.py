"""Тесты моделей расхода насоса."""

import pytest

from plant_control.domain.errors import InvalidFlowCurveError
from plant_control.domain.flow import ConstantFlow, LinearFlow, TableFlow


def test_constant_flow_ignores_head() -> None:
    curve = ConstantFlow(flow_ml_s=5)
    assert curve.flow_at(0) == 5
    assert curve.flow_at(1000) == 5


@pytest.mark.parametrize(
    ("head", "expected"),
    [(0, 6.0), (600, 3.0), (1200, 0.0), (2000, 0.0), (-100, 6.0)],
)
def test_linear_flow(head: float, expected: float) -> None:
    curve = LinearFlow(max_flow_ml_s=6, max_head_mm=1200)
    assert curve.flow_at(head) == pytest.approx(expected)


def test_table_flow_interpolates_between_points() -> None:
    curve = TableFlow(points=((0, 6.0), (500, 4.0), (1000, 0.0)))
    assert curve.flow_at(250) == pytest.approx(5.0)
    assert curve.flow_at(750) == pytest.approx(2.0)


def test_table_flow_clamps_outside_points() -> None:
    curve = TableFlow(points=((100, 6.0), (1000, 1.0)))
    assert curve.flow_at(0) == pytest.approx(6.0)
    assert curve.flow_at(5000) == pytest.approx(1.0)


def test_table_flow_rejects_unsorted_heads() -> None:
    with pytest.raises(InvalidFlowCurveError):
        TableFlow(points=((500, 4.0), (0, 6.0)))


def test_linear_flow_rejects_non_positive_values() -> None:
    with pytest.raises(InvalidFlowCurveError):
        LinearFlow(max_flow_ml_s=0, max_head_mm=1000)
