"""Поливальная машина - корень агрегата.

Владеет насосом, баком и (необязательно) коллектором. Умеет спланировать полив
по маршруту и зафиксировать его начало и конец. Сама ничего не включает:
последовательность "клапан, насос, пауза" исполняет слой application.
"""

from datetime import datetime

from plant_control.domain.calibration import FlowProfile
from plant_control.domain.collector import Collector
from plant_control.domain.connection import Route
from plant_control.domain.errors import (
    CalibrationStaleError,
    InvalidMachineError,
    MachineBusyError,
    RouteNotCalibratedError,
    UnknownRouteError,
)
from plant_control.domain.pump import Pump
from plant_control.domain.tank import Tank
from plant_control.domain.tuning import FlowSuggestion, FlowTracker, TuningThresholds
from plant_control.domain.watering import (
    HeadModel,
    Plumbing,
    WateringPlan,
    calculate_calibrated_watering,
    calculate_watering,
)


class WateringMachine:
    """Маршруты хранятся по ключу:
    - с коллектором ключ - id клапана, который ведёт к растению;
    - без коллектора маршрут ровно один, ключ любой.

    Два режима расчёта:
    - по калибровке: profiles задан, у каждого маршрута свой профиль расхода
      (свой замер или унаследованный от базового маршрута);
    - по паспорту: profiles = None, расход из паспорта насоса, напор, обвязка.
    """

    def __init__(
        self,
        machine_id: str,
        *,
        pump: Pump,
        tank: Tank,
        head_model: HeadModel,
        plumbing: Plumbing,
        routes: dict[str, Route],
        collector: Collector | None = None,
        supply_is_filled: bool = False,
        profiles: dict[str, FlowProfile] | None = None,
        flow_tracker: FlowTracker | None = None,
        stale_routes: frozenset[str] = frozenset(),
    ) -> None:
        if not routes:
            raise InvalidMachineError("machine needs at least one route")
        if plumbing.requires_collector and collector is None:
            raise InvalidMachineError("plumbing requires a collector, but none is given")
        if not plumbing.requires_collector and collector is not None:
            raise InvalidMachineError("collector is given, but plumbing does not use it")
        if collector is None and len(routes) != 1:
            raise InvalidMachineError("machine without collector must have exactly one route")
        if collector is not None:
            for route_id in routes:
                # Бросит UnknownValveError, если у коллектора нет такого клапана.
                collector.valve_state(route_id)
        if profiles is not None:
            unknown = set(profiles) - set(routes)
            if unknown:
                raise InvalidMachineError(f"profiles for unknown routes: {sorted(unknown)}")

        self._id = machine_id
        self._pump = pump
        self._tank = tank
        self._head_model = head_model
        self._plumbing = plumbing
        self._routes = dict(routes)
        self._collector = collector
        # Заполнена ли трубка от бака до коллектора. Хранится вместе с машиной.
        self._supply_is_filled = supply_is_filled
        # None - режим паспорта. Пустой словарь - режим калибровки, но замеров ещё нет.
        self._profiles = dict(profiles) if profiles is not None else None
        self._flow_tracker = flow_tracker or FlowTracker()
        # Маршруты, калибровка которых сделана на другом железе. Поливать их нельзя.
        self._stale_routes = frozenset(stale_routes) & set(routes)
        # Текущий полив. None - машина свободна.
        self._current: WateringPlan | None = None

    @property
    def id(self) -> str:
        return self._id

    @property
    def pump(self) -> Pump:
        return self._pump

    @property
    def tank(self) -> Tank:
        return self._tank

    @property
    def collector(self) -> Collector | None:
        return self._collector

    @property
    def route_ids(self) -> list[str]:
        return list(self._routes)

    @property
    def supply_is_filled(self) -> bool:
        return self._supply_is_filled

    @property
    def uses_calibration(self) -> bool:
        return self._profiles is not None

    @property
    def stale_routes(self) -> frozenset[str]:
        """Маршруты с устаревшей калибровкой. В режиме паспорта всегда пусто."""
        return self._stale_routes if self.uses_calibration else frozenset()

    def profile_for(self, route_id: str) -> FlowProfile | None:
        """Профиль расхода маршрута. None - режим паспорта или замера ещё нет."""
        self._route(route_id)
        return self._profiles.get(route_id) if self._profiles is not None else None

    @property
    def flow_tracker(self) -> FlowTracker:
        return self._flow_tracker

    @property
    def is_busy(self) -> bool:
        return self._current is not None

    def valve_for(self, route_id: str) -> str | None:
        """Какой клапан открыть для маршрута. None - коллектора нет."""
        self._route(route_id)
        return route_id if self._collector is not None else None

    # --- Полив ---

    def plan_watering(self, route_id: str, dose_ml: float, now: datetime) -> WateringPlan:
        """Проверяет правила и считает полив. Состояние не меняет."""
        if self.is_busy:
            raise MachineBusyError(f"machine {self._id!r} is already watering")
        route = self._route(route_id)
        if self._collector is not None:
            self._collector.check_can_open(route_id)

        plan = self._calculate(route_id, route, dose_ml)
        # Насос проверяет, можно ли ему работать столько, сколько насчитали.
        self._pump.check_can_start(now, plan.duration)
        return plan

    def begin_watering(self, plan: WateringPlan) -> None:
        """Полив начался. Второй полив до окончания первого не допускается."""
        if self.is_busy:
            raise MachineBusyError(f"machine {self._id!r} is already watering")
        self._current = plan

    def complete_watering(self, plan: WateringPlan) -> None:
        """Полив выполнен: списать воду, отметить, что трубка до коллектора полная."""
        self._tank.draw(plan.consumed_ml)
        self._flow_tracker = self._flow_tracker.with_watering(
            plan.consumed_ml, calibrated=self.uses_calibration
        )
        if self._plumbing.requires_collector:
            self._supply_is_filled = True
        self._current = None

    def abort_watering(self) -> None:
        """Полив прерван: воду не списываем, сколько пролилось, неизвестно."""
        self._current = None

    # --- Калибровка и бак ---

    def record_calibration_run(self, volume_ml: float) -> None:
        """Калибровочный прогон: списать фактически пролитое, трубка до коллектора полная."""
        self._tank.draw(min(volume_ml, self._tank.usable_volume_ml))
        if self._plumbing.requires_collector:
            self._supply_is_filled = True

    def measure_tank(
        self,
        volume_ml: float,
        now: datetime,
        thresholds: TuningThresholds | None = None,
    ) -> FlowSuggestion | None:
        """Человек сообщил фактический объём. Возвращает предложение поправить расход."""
        computed = self._tank.volume_ml
        self._tank.set_measured_volume(volume_ml)
        suggestion = None
        if self.uses_calibration:
            suggestion = self._flow_tracker.evaluate(computed, volume_ml, now, thresholds)
        self._flow_tracker = FlowTracker()
        return suggestion

    def fill_tank_full(self) -> None:
        """Долили до полного "на глаз": сравнение расхода начинается заново."""
        self._tank.fill_full()
        self._flow_tracker = FlowTracker()

    def mark_supply_empty(self) -> None:
        """Трубка до коллектора опустела (бак осушили, попал воздух)."""
        self._supply_is_filled = False

    # --- Внутреннее ---

    def _calculate(self, route_id: str, route: Route, dose_ml: float) -> WateringPlan:
        if self._profiles is not None:
            if route_id in self._stale_routes:
                raise CalibrationStaleError(f"calibration of route {route_id!r} is stale")
            profile = self._profiles.get(route_id)
            if profile is None:
                raise RouteNotCalibratedError(f"route {route_id!r} is not calibrated")
            return calculate_calibrated_watering(
                tank=self._tank,
                profile=profile,
                dose_ml=dose_ml,
                plumbing=self._plumbing,
                supply_is_filled=self._supply_is_filled,
            )
        flow = self._pump.passport.flow
        if flow is None:
            raise RouteNotCalibratedError("pump has no flow model and no calibration")
        return calculate_watering(
            tank=self._tank,
            flow=flow,
            route=route,
            dose_ml=dose_ml,
            plumbing=self._plumbing,
            head_model=self._head_model,
            supply_is_filled=self._supply_is_filled,
        )

    def _route(self, route_id: str) -> Route:
        try:
            return self._routes[route_id]
        except KeyError:
            # from None - не показывать KeyError в трассировке, наша ошибка понятнее.
            raise UnknownRouteError(f"unknown route {route_id!r}") from None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WateringMachine):
            return NotImplemented
        return self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return f"WateringMachine(id={self._id!r}, routes={list(self._routes)})"
