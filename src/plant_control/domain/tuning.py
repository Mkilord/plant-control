"""Автоподстройка расхода по фактическому уровню в баке.

Между двумя замерами уровня машина копит, сколько воды по расчёту ушло на поливы.
Когда человек вводит фактический объём, расчётный объём бака (до замены) и
фактический расходятся ровно на ошибку расчёта:

    фактически ушло = по расчёту ушло + (расчётный объём - фактический объём)

Если отношение заметно отличается от 1 и поливов было достаточно, предлагается
умножить расход в профилях на это отношение. Само ничего не меняется.

Долив известного объёма на сравнение не влияет: он одинаково попадает и в расчёт,
и в бак. Долив без записи сравнение портит, его не отличить от ошибки расчёта,
поэтому "долить до полного" начинает сравнение заново, а отрицательный
фактический расход сравнение отменяет.
"""

from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TuningThresholds:
    # Отклонение, после которого предлагать поправку, %.
    deviation_pct: float = 10.0
    min_waterings: int = 3


@dataclass(frozen=True, slots=True)
class FlowSuggestion:
    # Во сколько раз умножить расход: больше 1 - насос даёт больше, чем считали.
    factor: float
    expected_ml: float
    actual_ml: float
    waterings: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FlowTracker:
    """Сколько воды ушло на поливы по расчёту с последнего замера уровня.

    valid=False - был полив не по калибровке, сравнивать нечего до следующего замера.
    """

    expected_ml: float = 0.0
    waterings: int = 0
    valid: bool = True

    def with_watering(self, consumed_ml: float, calibrated: bool) -> "FlowTracker":
        if not calibrated:
            return replace(self, valid=False)
        return replace(
            self, expected_ml=self.expected_ml + consumed_ml, waterings=self.waterings + 1
        )

    def evaluate(
        self,
        computed_volume_ml: float,
        measured_volume_ml: float,
        now: datetime,
        thresholds: TuningThresholds | None = None,
    ) -> FlowSuggestion | None:
        limits = thresholds or TuningThresholds()
        if not self.valid or self.waterings < limits.min_waterings or self.expected_ml <= 0:
            return None
        actual = self.expected_ml + (computed_volume_ml - measured_volume_ml)
        if actual <= 0:
            return None
        factor = actual / self.expected_ml
        if abs(factor - 1) * 100 <= limits.deviation_pct:
            return None
        return FlowSuggestion(factor, self.expected_ml, actual, self.waterings, now)
