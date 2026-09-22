"""Соединение (трубка), выход воды у растения и маршрут до растения."""

import math
from dataclasses import dataclass

from plant_control.domain.errors import InvalidConnectionError
from plant_control.domain.tank import MM3_PER_ML


@dataclass(frozen=True, slots=True)
class Connection:
    """Трубка. Внутренний объём - сколько воды в ней помещается."""

    length_mm: float
    inner_radius_mm: float

    def __post_init__(self) -> None:
        if self.length_mm < 0:
            raise InvalidConnectionError(f"length_mm must be non-negative, got {self.length_mm}")
        if self.inner_radius_mm <= 0:
            raise InvalidConnectionError(
                f"inner_radius_mm must be positive, got {self.inner_radius_mm}"
            )

    @property
    def dead_volume_ml(self) -> float:
        return math.pi * self.inner_radius_mm**2 * self.length_mm / MM3_PER_ML


@dataclass(frozen=True, slots=True)
class Outlet:
    """Выход воды у растения. Высота от дна бака нужна, чтобы посчитать напор."""

    height_above_tank_bottom_mm: float


@dataclass(frozen=True, slots=True)
class Route:
    """Маршрут до растения.

    connection - трубка до растения: без коллектора это единственная трубка от бака,
    с коллектором - трубка от клапана до растения.
    correction - поправка расхода для этого маршрута (потери в трубке, клапане),
    подбирается калибровкой. 1.0 - без поправки.
    """

    connection: Connection
    outlet: Outlet
    correction: float = 1.0

    def __post_init__(self) -> None:
        if self.correction <= 0:
            raise InvalidConnectionError(f"correction must be positive, got {self.correction}")
