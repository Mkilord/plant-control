"""Модели расхода насоса: сколько мл/с он даёт при заданном напоре.

Напор (мм) - на какую высоту насос поднимает воду: от поверхности в баке до выхода.
"""

from dataclasses import dataclass
from typing import Protocol

from plant_control.domain.errors import InvalidFlowCurveError


class FlowCurve(Protocol):
    """Расход насоса (мл/с) при напоре (мм). 0 значит, что насос не поднимет воду."""

    def flow_at(self, head_mm: float) -> float: ...


# Отрицательный напор (выход ниже уровня воды) во всех моделях считается нулевым:
# самотёк и сифон не моделируем.


@dataclass(frozen=True, slots=True)
class ConstantFlow:
    """Напор не учитывается. Самая простая модель, точка отсчёта для сравнения."""

    flow_ml_s: float

    def __post_init__(self) -> None:
        if self.flow_ml_s <= 0:
            raise InvalidFlowCurveError(f"flow_ml_s must be positive, got {self.flow_ml_s}")

    def flow_at(self, head_mm: float) -> float:
        return self.flow_ml_s


@dataclass(frozen=True, slots=True)
class LinearFlow:
    """Расход линейно падает от max_flow при нулевом напоре до нуля при max_head.

    Два числа из паспорта насоса. Реальные кривые выгнутые, но для начала годится.
    """

    max_flow_ml_s: float
    max_head_mm: float

    def __post_init__(self) -> None:
        if self.max_flow_ml_s <= 0:
            raise InvalidFlowCurveError(f"max_flow_ml_s must be positive, got {self.max_flow_ml_s}")
        if self.max_head_mm <= 0:
            raise InvalidFlowCurveError(f"max_head_mm must be positive, got {self.max_head_mm}")

    def flow_at(self, head_mm: float) -> float:
        head = max(0.0, head_mm)
        if head >= self.max_head_mm:
            return 0.0
        return self.max_flow_ml_s * (1 - head / self.max_head_mm)


@dataclass(frozen=True, slots=True)
class TableFlow:
    """Кривая по точкам (напор мм, расход мл/с) с линейной интерполяцией между ними.

    Точки берутся с графика в паспорте или из калибровки.
    До первой точки расход как в первой, после последней - как в последней.
    """

    # tuple[tuple[float, float], ...] - неизменяемый список пар любой длины.
    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise InvalidFlowCurveError("need at least 2 points")
        heads = [head for head, _ in self.points]
        # zip(a, a[1:]) - пары соседних элементов: (a0, a1), (a1, a2), ...
        if any(next_head <= head for head, next_head in zip(heads, heads[1:], strict=False)):
            raise InvalidFlowCurveError("heads must be strictly increasing")
        if any(flow < 0 for _, flow in self.points):
            raise InvalidFlowCurveError("flows must be non-negative")

    def flow_at(self, head_mm: float) -> float:
        head = max(0.0, head_mm)
        first_head, first_flow = self.points[0]
        last_head, last_flow = self.points[-1]
        if head <= first_head:
            return first_flow
        if head >= last_head:
            return last_flow
        for (h0, q0), (h1, q1) in zip(self.points, self.points[1:], strict=False):
            if h0 <= head <= h1:
                return q0 + (q1 - q0) * (head - h0) / (h1 - h0)
        return last_flow  # сюда не дойдём, нужно для mypy
