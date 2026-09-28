"""Бак: форма (сменная стратегия), текущий объём воды, высота забора насоса.

Единицы во всём расчёте: длины в мм, объёмы в мл. 1 мл = 1000 мм^3.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, Self

from plant_control.domain.errors import (
    InvalidTankError,
    NotEnoughWaterError,
    TankOverflowError,
)

MM3_PER_ML = 1000.0

# Допуск для сравнения float: 1e-9 мл заведомо меньше любой реальной погрешности.
EPSILON = 1e-9


class TankGeometry(Protocol):
    """Форма бака. Связывает уровень воды (мм от дна) и объём (мл)."""

    @property
    def height_mm(self) -> float: ...

    def capacity_ml(self) -> float: ...

    def volume_at_level(self, level_mm: float) -> float: ...

    def level_at_volume(self, volume_ml: float) -> float: ...


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _require_positive(**values: float) -> None:
    # **values - именованные аргументы как словарь: _require_positive(diameter_mm=200)
    for name, value in values.items():
        if value <= 0:
            raise InvalidTankError(f"{name} must be positive, got {value}")


def level_by_bisection(
    volume_at_level: Callable[[float], float],
    height_mm: float,
    volume_ml: float,
    iterations: int = 60,
) -> float:
    """Подбирает уровень по объёму делением отрезка пополам.

    Годится для любой формы, у которой объём растёт с уровнем,
    но обратной формулы нет (горизонтальный цилиндр, конус, шар).
    60 итераций сужают отрезок в 2^60 раз, этого с запасом хватает.
    """
    low, high = 0.0, height_mm
    for _ in range(iterations):
        mid = (low + high) / 2
        if volume_at_level(mid) < volume_ml:
            low = mid
        else:
            high = mid
    return (low + high) / 2


@dataclass(frozen=True, slots=True)
class VerticalCylinder:
    """Цилиндр стоя, как ведро. Уровень линейно зависит от объёма."""

    diameter_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        _require_positive(diameter_mm=self.diameter_mm, height_mm=self.height_mm)

    def _area_mm2(self) -> float:
        return math.pi * (self.diameter_mm / 2) ** 2

    def capacity_ml(self) -> float:
        return self.volume_at_level(self.height_mm)

    def volume_at_level(self, level_mm: float) -> float:
        level = _clamp(level_mm, 0.0, self.height_mm)
        return self._area_mm2() * level / MM3_PER_ML

    def level_at_volume(self, volume_ml: float) -> float:
        volume = _clamp(volume_ml, 0.0, self.capacity_ml())
        return volume * MM3_PER_ML / self._area_mm2()


@dataclass(frozen=True, slots=True)
class HorizontalCylinder:
    """Цилиндр лёжа, как бочка. Уровень падает неравномерно:
    в середине медленно, у дна и у верха быстро."""

    diameter_mm: float
    length_mm: float

    def __post_init__(self) -> None:
        _require_positive(diameter_mm=self.diameter_mm, length_mm=self.length_mm)

    @property
    def height_mm(self) -> float:
        return self.diameter_mm

    def capacity_ml(self) -> float:
        return self.volume_at_level(self.height_mm)

    def volume_at_level(self, level_mm: float) -> float:
        # Площадь сегмента круга, залитого до высоты h.
        r = self.diameter_mm / 2
        h = _clamp(level_mm, 0.0, self.diameter_mm)
        segment_mm2 = r * r * math.acos((r - h) / r) - (r - h) * math.sqrt(
            max(0.0, 2 * r * h - h * h)
        )
        return segment_mm2 * self.length_mm / MM3_PER_ML

    def level_at_volume(self, volume_ml: float) -> float:
        volume = _clamp(volume_ml, 0.0, self.capacity_ml())
        return level_by_bisection(self.volume_at_level, self.height_mm, volume)


@dataclass(frozen=True, slots=True)
class RectangularTank:
    """Прямоугольный бак. Как вертикальный цилиндр, уровень линеен по объёму."""

    width_mm: float
    depth_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        _require_positive(width_mm=self.width_mm, depth_mm=self.depth_mm, height_mm=self.height_mm)

    def capacity_ml(self) -> float:
        return self.volume_at_level(self.height_mm)

    def volume_at_level(self, level_mm: float) -> float:
        level = _clamp(level_mm, 0.0, self.height_mm)
        return self.width_mm * self.depth_mm * level / MM3_PER_ML

    def level_at_volume(self, volume_ml: float) -> float:
        volume = _clamp(volume_ml, 0.0, self.capacity_ml())
        return volume * MM3_PER_ML / (self.width_mm * self.depth_mm)


@dataclass(frozen=True, slots=True)
class MeasuredTank:
    """Бак по замеру: объём воды до линии налива и высота воды при этом объёме.

    Форма не нужна. Бак считается "эквивалентным цилиндром" со средней площадью
    volume / height, поэтому неровные стенки (банка, ведро с конусом) уже учтены
    замером, а пустое место над линией налива в расчёт не входит.
    """

    volume_ml: float
    height_mm: float

    def __post_init__(self) -> None:
        _require_positive(volume_ml=self.volume_ml, height_mm=self.height_mm)

    def capacity_ml(self) -> float:
        return self.volume_ml

    def volume_at_level(self, level_mm: float) -> float:
        level = _clamp(level_mm, 0.0, self.height_mm)
        return self.volume_ml * level / self.height_mm

    def level_at_volume(self, volume_ml: float) -> float:
        volume = _clamp(volume_ml, 0.0, self.volume_ml)
        return self.height_mm * volume / self.volume_ml


class Tank:
    """Бак: форма, сколько в нём воды и с какой высоты забирает насос.

    Вода ниже забора насосу недоступна, поэтому проверки идут по доступному объёму.
    """

    def __init__(
        self,
        geometry: TankGeometry,
        volume_ml: float = 0.0,
        intake_height_mm: float = 0.0,
    ) -> None:
        if not 0 <= volume_ml <= geometry.capacity_ml() + EPSILON:
            raise InvalidTankError(
                f"volume_ml must be within 0..{geometry.capacity_ml():.1f}, got {volume_ml}"
            )
        if not 0 <= intake_height_mm < geometry.height_mm:
            raise InvalidTankError(
                f"intake_height_mm must be within 0..{geometry.height_mm}, got {intake_height_mm}"
            )
        self._geometry = geometry
        self._volume_ml = volume_ml
        self._intake_height_mm = intake_height_mm

    @classmethod
    def with_reserve(
        cls,
        geometry: TankGeometry,
        reserve_ml: float,
        volume_ml: float | None = None,
    ) -> Self:
        """Бак, у которого нижние reserve_ml недоступны насосу.

        Удобно, когда запас известен в мл, а не высотой забора.
        classmethod - аналог статического фабричного метода в Java.
        """
        intake = geometry.level_at_volume(reserve_ml)
        volume = geometry.capacity_ml() if volume_ml is None else volume_ml
        return cls(geometry, volume_ml=volume, intake_height_mm=intake)

    @property
    def geometry(self) -> TankGeometry:
        return self._geometry

    @property
    def volume_ml(self) -> float:
        return self._volume_ml

    @property
    def intake_height_mm(self) -> float:
        return self._intake_height_mm

    @property
    def level_mm(self) -> float:
        return self._geometry.level_at_volume(self._volume_ml)

    @property
    def unusable_volume_ml(self) -> float:
        """Объём ниже забора насоса."""
        return self._geometry.volume_at_level(self._intake_height_mm)

    @property
    def usable_volume_ml(self) -> float:
        return max(0.0, self._volume_ml - self.unusable_volume_ml)

    def check_can_draw(self, volume_ml: float) -> None:
        if volume_ml > self.usable_volume_ml + EPSILON:
            raise NotEnoughWaterError(
                f"need {volume_ml:.1f} ml, usable {self.usable_volume_ml:.1f} ml"
            )

    def draw(self, volume_ml: float) -> None:
        """Списать пролитый объём."""
        self.check_can_draw(volume_ml)
        self._volume_ml = max(0.0, self._volume_ml - volume_ml)

    def fill(self, volume_ml: float) -> None:
        """Долить воду."""
        if self._volume_ml + volume_ml > self._geometry.capacity_ml() + EPSILON:
            raise TankOverflowError(
                f"adding {volume_ml:.1f} ml exceeds capacity {self._geometry.capacity_ml():.1f} ml"
            )
        self._volume_ml += volume_ml

    def set_measured_volume(self, volume_ml: float) -> None:
        """Объём измерен вручную (посмотрели на уровень). Заменяет расчётный."""
        if not 0 <= volume_ml <= self._geometry.capacity_ml() + EPSILON:
            raise InvalidTankError(
                f"volume_ml must be within 0..{self._geometry.capacity_ml():.1f}, got {volume_ml}"
            )
        self._volume_ml = min(volume_ml, self._geometry.capacity_ml())

    def fill_full(self) -> None:
        self._volume_ml = self._geometry.capacity_ml()

    def __repr__(self) -> str:
        return (
            f"Tank(geometry={self._geometry!r}, volume_ml={self._volume_ml:.1f}, "
            f"level_mm={self.level_mm:.1f})"
        )
