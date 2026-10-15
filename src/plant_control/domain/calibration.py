"""Калибровка насоса замером: профиль расхода маршрута и обработка прогонов.

Профиль заменяет паспорт насоса, высоту выхода, долю стока в бак и поправку:
все эти эффекты уже входят в замер, сделанный на реальном выходе маршрута.

Время полива по профилю:
    t = prime_s + (dose_ml - afterflow_ml) / flow_ml_s

- flow_ml_s - расход в установившемся режиме;
- prime_s - задержка от включения до первой воды на выходе (реле плюс заполнение трубки);
- afterflow_ml - сколько дотекает в растение после выключения.

Расход может зависеть от уровня в баке (маленький бак, высокий выход).
Тогда в профиле две точки (объём в баке, расход), между ними и за ними -
прямая. Одна точка - расход постоянный.
"""

import math
import statistics
from dataclasses import dataclass, replace
from enum import Enum

from plant_control.domain.errors import CalibrationError, PumpCannotDeliverError

# Меньше этого расхода считаем, что насос воду не даёт. Нужен, чтобы прямая
# по двум уровням не ушла в ноль или минус при экстраполяции.
MIN_FLOW_FRACTION = 0.1


@dataclass(frozen=True, slots=True)
class FlowPoint:
    """Расход при заданном объёме воды в баке."""

    tank_volume_ml: float
    flow_ml_s: float

    def __post_init__(self) -> None:
        if self.tank_volume_ml < 0:
            raise CalibrationError(
                f"tank_volume_ml must be non-negative, got {self.tank_volume_ml}"
            )
        if self.flow_ml_s <= 0:
            raise CalibrationError(f"flow_ml_s must be positive, got {self.flow_ml_s}")


@dataclass(frozen=True, slots=True)
class FlowProfile:
    points: tuple[FlowPoint, ...]
    prime_s: float = 0.0
    afterflow_ml: float = 0.0

    def __post_init__(self) -> None:
        if not 1 <= len(self.points) <= 2:
            raise CalibrationError(f"need 1 or 2 flow points, got {len(self.points)}")
        if len(self.points) == 2 and math.isclose(
            self.points[0].tank_volume_ml, self.points[1].tank_volume_ml
        ):
            raise CalibrationError("flow points must be at different tank volumes")
        if self.prime_s < 0:
            raise CalibrationError(f"prime_s must be non-negative, got {self.prime_s}")
        if self.afterflow_ml < 0:
            raise CalibrationError(f"afterflow_ml must be non-negative, got {self.afterflow_ml}")

    @property
    def reference_flow_ml_s(self) -> float:
        """Расход первой точки: по нему считаются объёмы задержки."""
        return self.points[0].flow_ml_s

    @property
    def prime_ml(self) -> float:
        """Сколько уходит из бака, пока вода идёт до выхода. Оценка сверху:
        в prime_s входит и задержка реле, когда вода ещё не течёт."""
        return self.prime_s * self.reference_flow_ml_s

    @property
    def is_level_dependent(self) -> bool:
        return len(self.points) == 2

    def flow_at(self, tank_volume_ml: float) -> float:
        if len(self.points) == 1:
            return self.points[0].flow_ml_s
        a, b = sorted(self.points, key=lambda p: p.tank_volume_ml)
        slope = (b.flow_ml_s - a.flow_ml_s) / (b.tank_volume_ml - a.tank_volume_ml)
        flow = a.flow_ml_s + slope * (tank_volume_ml - a.tank_volume_ml)
        floor = MIN_FLOW_FRACTION * min(a.flow_ml_s, b.flow_ml_s)
        if flow < floor:
            raise PumpCannotDeliverError(
                f"calibrated flow at tank volume {tank_volume_ml:.0f} ml is too low"
            )
        return flow

    def scaled(self, factor: float) -> "FlowProfile":
        """Тот же профиль с расходом, умноженным на factor (автоподстройка)."""
        if factor <= 0:
            raise CalibrationError(f"factor must be positive, got {factor}")
        points = tuple(FlowPoint(p.tank_volume_ml, p.flow_ml_s * factor) for p in self.points)
        return replace(self, points=points)

    def inherited(self, tube_delta_ml: float) -> "FlowProfile":
        """Профиль для маршрута, у которого трубка больше базовой на tube_delta_ml.

        Расход тот же. Лишний объём трубки надо сначала заполнить (задержка растёт),
        а после выключения он стекает в растение (дотек растёт). Меньшая трубка -
        наоборот. Ниже нуля не опускаемся.
        """
        flow = self.reference_flow_ml_s
        return replace(
            self,
            prime_s=max(0.0, self.prime_s + tube_delta_ml / flow),
            afterflow_ml=max(0.0, self.afterflow_ml + tube_delta_ml),
        )

    def with_second_level(self, point: FlowPoint) -> "FlowProfile":
        """Добавить замер при другом уровне: расход станет зависеть от объёма в баке."""
        return replace(self, points=(self.points[0], point))


# --- Обработка замеров ---


class CalibrationMethod(Enum):
    MARKS = "marks"
    TIMED = "timed"


class CalibrationWarning(Enum):
    # Замер слишком короткий: ошибка нажатия заметна.
    TOO_FAST = "too_fast"
    # Точки далеко от прямой.
    HIGH_SPREAD = "high_spread"
    # Расход заметно падал по ходу замера: похоже, зависит от уровня в баке.
    FLOW_DROPS = "flow_drops"
    # Один прогон по времени: задержку посчитать нельзя, принята нулевой.
    NO_PRIME = "no_prime"


@dataclass(frozen=True, slots=True)
class LineFit:
    slope: float
    intercept: float
    # Среднеквадратичное отклонение точек от прямой, в единицах y.
    rms: float


def fit_line(points: list[tuple[float, float]]) -> LineFit:
    """Прямая y = slope * x + intercept методом наименьших квадратов."""
    if len(points) < 2:
        raise CalibrationError("need at least 2 points")
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        raise CalibrationError("points must differ in time")
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    rms = math.sqrt(statistics.fmean((y - (slope * x + intercept)) ** 2 for x, y in points))
    return LineFit(slope, intercept, rms)


@dataclass(frozen=True, slots=True)
class CalibrationThresholds:
    min_duration_s: float = 20.0
    max_spread_pct: float = 5.0
    # Насколько должен упасть расход от первого отрезка к последнему, чтобы предупредить.
    flow_drop_pct: float = 10.0


@dataclass(frozen=True, slots=True)
class RunResult:
    flow_ml_s: float
    prime_s: float
    afterflow_ml: float
    # Разброс точек вокруг прямой, % от наибольшего объёма. None - точек ровно две.
    spread_pct: float | None
    duration_s: float
    warnings: tuple[CalibrationWarning, ...] = ()


def _spread(fit: LineFit, n_points: int, max_volume: float) -> float | None:
    if n_points <= 2 or max_volume <= 0:
        return None
    return fit.rms / max_volume * 100


def evaluate_marks_run(
    marks: list[tuple[float, float]],
    final_volume_ml: float,
    water_started_s: float | None = None,
    thresholds: CalibrationThresholds | None = None,
) -> RunResult:
    """Прогон по меткам.

    marks - (секунд от включения, мл в ёмкости) в момент нажатия метки.
    Насос выключается на последней метке, final_volume_ml - объём в ёмкости,
    когда перестало капать. water_started_s - когда нажали "вода пошла" (точка с нулём).
    """
    limits = thresholds or CalibrationThresholds()
    if not marks:
        raise CalibrationError("need at least one mark")
    times = [t for t, _ in marks]
    volumes = [v for _, v in marks]
    if any(t <= 0 for t in times):
        raise CalibrationError("mark times must be positive")
    if any(b <= a for a, b in zip(times, times[1:], strict=False)):
        raise CalibrationError("mark times must increase")
    if any(v <= 0 for v in volumes) or any(
        b <= a for a, b in zip(volumes, volumes[1:], strict=False)
    ):
        raise CalibrationError("mark volumes must be positive and increase")

    points = list(marks)
    if water_started_s is not None:
        if not 0 <= water_started_s < times[0]:
            raise CalibrationError("water must start before the first mark")
        points.insert(0, (water_started_s, 0.0))
    if len(points) < 2:
        raise CalibrationError("one mark is not enough: add marks or press 'water started'")

    fit = fit_line(points)
    if fit.slope <= 0:
        raise CalibrationError("volume does not grow with time")
    flow = fit.slope
    prime = max(0.0, -fit.intercept / flow)
    last_volume = volumes[-1]
    if final_volume_ml + 1e-9 < last_volume:
        raise CalibrationError("final volume is less than the last mark")
    afterflow = final_volume_ml - last_volume

    warnings: list[CalibrationWarning] = []
    duration = times[-1]
    if duration < limits.min_duration_s:
        warnings.append(CalibrationWarning.TOO_FAST)
    spread = _spread(fit, len(points), last_volume)
    if spread is not None and spread > limits.max_spread_pct:
        warnings.append(CalibrationWarning.HIGH_SPREAD)
    if len(points) >= 3:
        first = (points[1][1] - points[0][1]) / (points[1][0] - points[0][0])
        last = (points[-1][1] - points[-2][1]) / (points[-1][0] - points[-2][0])
        if first > 0 and (first - last) / first * 100 > limits.flow_drop_pct:
            warnings.append(CalibrationWarning.FLOW_DROPS)

    return RunResult(flow, prime, afterflow, spread, duration, tuple(warnings))


def evaluate_timed_runs(
    runs: list[tuple[float, float]],
    thresholds: CalibrationThresholds | None = None,
) -> RunResult:
    """Прогоны по времени: (сколько секунд работал насос, сколько мл набралось).

    Дотек входит в объём каждого прогона, поэтому afterflow = 0, а задержка
    получается эффективной: "сколько секунд работы не доходит до растения".
    """
    limits = thresholds or CalibrationThresholds()
    if not runs:
        raise CalibrationError("need at least one run")
    if any(d <= 0 for d, _ in runs) or any(v <= 0 for _, v in runs):
        raise CalibrationError("durations and volumes must be positive")

    warnings: list[CalibrationWarning] = []
    durations = {d for d, _ in runs}
    if len(durations) == 1:
        # Все прогоны одной длины: только средний расход.
        flow = statistics.fmean(v for _, v in runs) / runs[0][0]
        prime = 0.0
        spread = None
        if len(runs) > 1:
            volumes = [v for _, v in runs]
            spread = statistics.pstdev(volumes) / max(volumes) * 100
        warnings.append(CalibrationWarning.NO_PRIME)
    else:
        fit = fit_line(runs)
        if fit.slope <= 0:
            raise CalibrationError("volume does not grow with run time")
        flow = fit.slope
        prime = max(0.0, -fit.intercept / flow)
        spread = _spread(fit, len(runs), max(v for _, v in runs))

    if max(durations) < limits.min_duration_s:
        warnings.append(CalibrationWarning.TOO_FAST)
    if spread is not None and spread > limits.max_spread_pct:
        warnings.append(CalibrationWarning.HIGH_SPREAD)
    return RunResult(flow, prime, 0.0, spread, max(durations), tuple(warnings))


def combine_runs(results: list[RunResult]) -> RunResult:
    """Среднее нескольких прогонов по меткам. Предупреждения собираются со всех."""
    if not results:
        raise CalibrationError("no runs to combine")
    if len(results) == 1:
        return results[0]
    flows = [r.flow_ml_s for r in results]
    warnings: list[CalibrationWarning] = []
    for result in results:
        for warning in result.warnings:
            if warning not in warnings:
                warnings.append(warning)
    # Разброс между прогонами: насколько расходы прогонов отличаются друг от друга.
    spread = statistics.pstdev(flows) / statistics.fmean(flows) * 100
    return RunResult(
        flow_ml_s=statistics.fmean(flows),
        prime_s=statistics.fmean(r.prime_s for r in results),
        afterflow_ml=statistics.fmean(r.afterflow_ml for r in results),
        spread_pct=spread,
        duration_s=max(r.duration_s for r in results),
        warnings=tuple(warnings),
    )


def profile_from(result: RunResult, tank_volume_ml: float) -> FlowProfile:
    return FlowProfile(
        points=(FlowPoint(tank_volume_ml, result.flow_ml_s),),
        prime_s=result.prime_s,
        afterflow_ml=result.afterflow_ml,
    )
