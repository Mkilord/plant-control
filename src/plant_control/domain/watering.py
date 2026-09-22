"""Расчёт полива: сколько секунд держать насос, чтобы растение получило дозу.

Все физические допущения вынесены в сменные стратегии:
- форма бака (tank.TankGeometry),
- модель расхода насоса (flow.FlowCurve),
- обвязка: как ведёт себя вода в трубках после выключения (Plumbing),
- какой напор брать, пока уровень падает во время полива (HeadModel).

Два объёма, которые важно различать:
- pumped - сколько насос прокачивает за полив. От него зависит время.
- consumed - сколько бак в итоге теряет. Часть прокачанного может стечь обратно.

Функция calculate_watering чистая: бак не меняет, только считает.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from plant_control.domain.connection import Connection, Outlet, Route
from plant_control.domain.errors import InvalidWateringRequestError, PumpCannotDeliverError
from plant_control.domain.flow import FlowCurve
from plant_control.domain.tank import Tank, TankGeometry

# --- Обвязка ---


@dataclass(frozen=True, slots=True)
class ExtraVolumes:
    """Сколько сверх дозы насос прокачивает и сколько сверх дозы теряет бак."""

    pumped_ml: float
    consumed_ml: float


class Plumbing(Protocol):
    """Как ведёт себя вода в трубках. Зависит от того, есть ли коллектор."""

    @property
    def requires_collector(self) -> bool: ...

    def extra_volumes(self, route: Route, supply_is_filled: bool) -> ExtraVolumes: ...


@dataclass(frozen=True, slots=True)
class DirectPlumbing:
    """Без коллектора: одна трубка от насоса до растения.

    После выключения насоса трубка пустеет: доля back_to_tank_fraction стекает
    обратно в бак через погружной насос, остальное вытекает в растение.

    Пусть V - объём трубки, f - доля обратно в бак, D - доза.
    Пока насос работает, растение получает прокачанное минус V (трубку надо заполнить).
    После выключения растение получает ещё (1 - f) * V.
    Значит, чтобы растение получило D, надо прокачать D + f * V,
    а бак потеряет ровно D: f * V вернётся обратно.
    """

    back_to_tank_fraction: float = 0.5

    def __post_init__(self) -> None:
        if not 0 <= self.back_to_tank_fraction <= 1:
            raise InvalidWateringRequestError(
                f"back_to_tank_fraction must be within 0..1, got {self.back_to_tank_fraction}"
            )

    @property
    def requires_collector(self) -> bool:
        return False

    def extra_volumes(self, route: Route, supply_is_filled: bool) -> ExtraVolumes:
        returned = route.connection.dead_volume_ml * self.back_to_tank_fraction
        return ExtraVolumes(pumped_ml=returned, consumed_ml=0.0)


@dataclass(frozen=True, slots=True)
class CollectorPlumbing:
    """С коллектором из нормально закрытых клапанов.

    Трубка от бака до коллектора (supply) остаётся полной: закрытый клапан держит
    столб воды, как палец на соломинке. Её объём проливается один раз,
    пока она пустая, и остаётся в трубке - бак его теряет.

    Трубка от клапана до растения после закрытия клапана стекает в растение,
    так что лишнего объёма на ней нет.
    """

    supply: Connection

    @property
    def requires_collector(self) -> bool:
        return True

    def extra_volumes(self, route: Route, supply_is_filled: bool) -> ExtraVolumes:
        prime = 0.0 if supply_is_filled else self.supply.dead_volume_ml
        return ExtraVolumes(pumped_ml=prime, consumed_ml=prime)


# --- Гидравлический контекст ---


@dataclass(frozen=True, slots=True)
class Hydraulics:
    """Всё, что нужно, чтобы по объёму воды в баке узнать напор и расход."""

    geometry: TankGeometry
    flow: FlowCurve
    outlet: Outlet
    correction: float = 1.0

    def head_at_volume(self, volume_ml: float) -> float:
        level = self.geometry.level_at_volume(volume_ml)
        return self.outlet.height_above_tank_bottom_mm - level

    def flow_at_volume(self, volume_ml: float) -> float:
        head = self.head_at_volume(volume_ml)
        flow = self.flow.flow_at(head) * self.correction
        if flow <= 0:
            raise PumpCannotDeliverError(f"pump gives no flow at head {head:.0f} mm")
        return flow


# --- Напор во время полива ---


class HeadModel(Protocol):
    """Как посчитать время пролива объёма, если уровень в баке падает по ходу."""

    def duration_s(
        self, hydraulics: Hydraulics, start_volume_ml: float, pumped_ml: float
    ) -> float: ...


@dataclass(frozen=True, slots=True)
class StartLevelHead:
    """Весь полив по напору в начале. Быстро и чуть оптимистично."""

    def duration_s(self, hydraulics: Hydraulics, start_volume_ml: float, pumped_ml: float) -> float:
        return pumped_ml / hydraulics.flow_at_volume(start_volume_ml)


@dataclass(frozen=True, slots=True)
class MidDoseHead:
    """Весь полив по напору в момент, когда прокачана половина объёма."""

    def duration_s(self, hydraulics: Hydraulics, start_volume_ml: float, pumped_ml: float) -> float:
        return pumped_ml / hydraulics.flow_at_volume(start_volume_ml - pumped_ml / 2)


@dataclass(frozen=True, slots=True)
class StepwiseHead:
    """Объём делится на steps частей, каждая считается по своему напору.
    Чем больше шагов, тем ближе к точному интегралу."""

    steps: int = 20

    def __post_init__(self) -> None:
        if self.steps < 1:
            raise InvalidWateringRequestError(f"steps must be >= 1, got {self.steps}")

    def duration_s(self, hydraulics: Hydraulics, start_volume_ml: float, pumped_ml: float) -> float:
        chunk = pumped_ml / self.steps
        total_s = 0.0
        for i in range(self.steps):
            mid_volume = start_volume_ml - chunk * (i + 0.5)
            total_s += chunk / hydraulics.flow_at_volume(mid_volume)
        return total_s


# --- Результат ---


@dataclass(frozen=True, slots=True)
class WateringPlan:
    """Результат расчёта с разбором: для экспериментов разбор важнее итога.

    level_end_mm - уровень в момент выключения насоса, до того как часть воды
    стечёт обратно в бак.
    """

    dose_ml: float
    pumped_ml: float
    consumed_ml: float
    level_start_mm: float
    level_end_mm: float
    head_start_mm: float
    head_end_mm: float
    flow_start_ml_s: float
    flow_end_ml_s: float
    duration_s: float

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=self.duration_s)

    @property
    def average_flow_ml_s(self) -> float:
        return self.pumped_ml / self.duration_s


# --- Расчёт ---


def calculate_watering(
    *,
    tank: Tank,
    flow: FlowCurve,
    route: Route,
    dose_ml: float,
    plumbing: Plumbing,
    head_model: HeadModel,
    supply_is_filled: bool = False,
) -> WateringPlan:
    """Считает полив. Бак не меняет: списать воду - забота вызывающего кода.

    Звёздочка в начале параметров означает, что все аргументы передаются только
    по имени: calculate_watering(tank=..., flow=...). Так их невозможно перепутать.
    """
    if dose_ml <= 0:
        raise InvalidWateringRequestError(f"dose_ml must be positive, got {dose_ml}")

    extra = plumbing.extra_volumes(route, supply_is_filled)
    pumped_ml = dose_ml + extra.pumped_ml
    consumed_ml = dose_ml + extra.consumed_ml

    # Пока насос работает, бак опускается на весь прокачанный объём,
    # поэтому проверяем по pumped, а не по consumed.
    tank.check_can_draw(pumped_ml)

    hydraulics = Hydraulics(tank.geometry, flow, route.outlet, route.correction)
    start_volume = tank.volume_ml
    end_volume = start_volume - pumped_ml

    # Расход в конце проверяем отдельно: к концу полива напор максимальный,
    # и насос может перестать поднимать воду раньше, чем закончится доза.
    flow_start = hydraulics.flow_at_volume(start_volume)
    flow_end = hydraulics.flow_at_volume(end_volume)

    return WateringPlan(
        dose_ml=dose_ml,
        pumped_ml=pumped_ml,
        consumed_ml=consumed_ml,
        level_start_mm=tank.geometry.level_at_volume(start_volume),
        level_end_mm=tank.geometry.level_at_volume(end_volume),
        head_start_mm=hydraulics.head_at_volume(start_volume),
        head_end_mm=hydraulics.head_at_volume(end_volume),
        flow_start_ml_s=flow_start,
        flow_end_ml_s=flow_end,
        duration_s=head_model.duration_s(hydraulics, start_volume, pumped_ml),
    )
