"""Мастер калибровки насоса: сессии замера, защита насоса, сохранение результата.

Сессия открывается на маршрут машины. Пока она открыта, машина занята:
поливы по кнопке и расписанию ждут. В сессии один или несколько прогонов.

Прогон по меткам:
    start - насос включён; mark - человек отметил объём в ёмкости
    (0 мл - "вода пошла"); на последней метке насос выключается сам;
    volume - итоговый объём, когда перестало капать.
Время меток считает клиент от момента, когда сервер подтвердил включение:
так сетевые задержки на каждом нажатии в замер не попадают.

Прогон по времени:
    run - насос работает ровно duration_s, включает и выключает сервер;
    volume - сколько набралось.

Защиты: ограничение насоса по времени работы, автостоп, если после первой метки
последняя не пришла к overtime_factor от ожидаемого времени, и автостоп без
heartbeat от клиента (страницу закрыли, пропала связь).
"""

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Literal

from plant_control.application.actuation import Actuation
from plant_control.domain.calibration import (
    CalibrationMethod,
    CalibrationThresholds,
    FlowPoint,
    RunResult,
    combine_runs,
    evaluate_marks_run,
    evaluate_timed_runs,
)
from plant_control.domain.collector import ValveState
from plant_control.domain.errors import (
    CalibrationError,
    MachineBusyError,
    PumpRuntimeExceededError,
    UnknownRouteError,
)
from plant_control.domain.tuning import TuningThresholds
from pydantic import BaseModel, Field

from plant_control_addon.config import (
    CollectorPlumbingConfig,
    FlowPointConfig,
    RouteCalibrationConfig,
    tube_volume_ml,
)
from plant_control_addon.registry import MachineEntry, MachineRegistry
from plant_control_addon.storage import MachineStore, StoredCalibration

log = logging.getLogger(__name__)

SETTINGS_KEY = "calibration"


class CalibrationSettings(BaseModel):
    """Пороги мастера и автоподстройки. Правятся в интерфейсе."""

    min_duration_s: float = Field(default=20, ge=0)
    max_spread_pct: float = Field(default=5, gt=0)
    # Автостоп, если последняя метка не пришла к этой доле от ожидаемого времени.
    overtime_factor: float = Field(default=1.5, ge=1.1)
    # Без heartbeat столько секунд во время прогона - насос выключается.
    heartbeat_timeout_s: float = Field(default=6, gt=0)
    # Без heartbeat столько секунд между прогонами - сессия закрывается.
    idle_timeout_s: float = Field(default=120, gt=0)
    tune_deviation_pct: float = Field(default=10, gt=0)
    tune_min_waterings: int = Field(default=3, ge=1)
    # Напоминать о повторной калибровке раз в N недель. None - не напоминать.
    reminder_weeks: int | None = Field(default=None, ge=1)
    # Второй уровень принимается, если объём в баке отличается хотя бы на столько % от бака.
    second_level_min_pct: float = Field(default=20, gt=0, le=100)

    def thresholds(self) -> CalibrationThresholds:
        return CalibrationThresholds(
            min_duration_s=self.min_duration_s, max_spread_pct=self.max_spread_pct
        )

    def tuning(self) -> TuningThresholds:
        return TuningThresholds(
            deviation_pct=self.tune_deviation_pct, min_waterings=self.tune_min_waterings
        )


class SessionState(Enum):
    # Можно начинать прогон.
    READY = "ready"
    RUNNING = "running"
    # Насос выключен, ждём объём в ёмкости.
    AWAITING_VOLUME = "awaiting_volume"
    CLOSED = "closed"


class StopReason(Enum):
    LAST_MARK = "last_mark"
    TIMER = "timer"
    USER = "user"
    OVERTIME = "overtime"
    HEARTBEAT = "heartbeat"
    MAX_RUNTIME = "max_runtime"
    ERROR = "error"

    @property
    def completes_run(self) -> bool:
        return self in (StopReason.LAST_MARK, StopReason.TIMER)


class CalibrationSessionError(Exception):
    """Действие не подходит к состоянию сессии: метка без прогона и так далее."""


class UnknownSessionError(Exception):
    pass


@dataclass
class Run:
    index: int
    started_at: datetime
    # Объём в баке перед прогоном и была ли полной трубка до коллектора.
    tank_volume_ml: float
    supply_filled: bool
    supply_ml: float
    marks: list[tuple[float, float]] = field(default_factory=list)
    water_started_s: float | None = None
    # Прогон по времени: сколько секунд должен работать насос.
    planned_s: float | None = None
    stop_reason: StopReason | None = None
    stopped_after_s: float | None = None
    volume_ml: float | None = None
    result: RunResult | None = None
    error: str | None = None
    excluded: bool = False

    @property
    def completed(self) -> bool:
        return (
            self.stop_reason is not None
            and self.stop_reason.completes_run
            and self.volume_ml is not None
            and self.error is None
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "started_at": self.started_at.isoformat(),
            "tank_volume_ml": self.tank_volume_ml,
            "supply_filled": self.supply_filled,
            "supply_ml": self.supply_ml,
            "marks": self.marks,
            "water_started_s": self.water_started_s,
            "planned_s": self.planned_s,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "stopped_after_s": self.stopped_after_s,
            "volume_ml": self.volume_ml,
            "result": result_json(self.result),
            "error": self.error,
            "excluded": self.excluded,
        }


def result_json(result: RunResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "flow_ml_s": result.flow_ml_s,
        "prime_s": result.prime_s,
        "afterflow_ml": result.afterflow_ml,
        "spread_pct": result.spread_pct,
        "duration_s": result.duration_s,
        "warnings": [w.value for w in result.warnings],
    }


@dataclass
class Session:
    id: str
    machine_id: str
    route_id: str
    method: CalibrationMethod
    # Метки в мл для режима меток, по возрастанию.
    targets: list[float]
    created_at: datetime
    state: SessionState = SessionState.READY
    runs: list[Run] = field(default_factory=list)
    last_heartbeat: float = 0.0
    run_started: float = 0.0
    deadline: float | None = None
    run_task: asyncio.Task[None] | None = None
    tank_volume_end_ml: float | None = None

    @property
    def current(self) -> Run | None:
        return self.runs[-1] if self.runs else None

    def result(self, thresholds: CalibrationThresholds) -> RunResult:
        """Итог по всем завершённым и не исключённым прогонам. Бросает CalibrationError."""
        runs = [run for run in self.runs if run.completed and not run.excluded]
        if not runs:
            raise CalibrationError("no completed runs")
        if self.method is CalibrationMethod.MARKS:
            results = [run.result for run in runs if run.result is not None]
            return combine_runs(results)
        points: list[tuple[float, float]] = []
        for run in runs:
            assert run.planned_s is not None and run.volume_ml is not None
            # Пустая трубка до коллектора забрала часть воды прогона: возвращаем её.
            extra = 0.0 if run.supply_filled else run.supply_ml
            points.append((run.planned_s, run.volume_ml + extra))
        return evaluate_timed_runs(points, thresholds)

    def reference_volume_ml(self) -> float:
        """Средний объём в баке за калибровку: к нему привязан расход."""
        runs = [run for run in self.runs if run.completed and not run.excluded]
        start = runs[0].tank_volume_ml if runs else 0.0
        end = self.tank_volume_end_ml if self.tank_volume_end_ml is not None else start
        return (start + end) / 2


class Hooks:
    """Что менеджеру нужно от контроллера: порты HA, проверка проблем, часы."""

    def __init__(
        self,
        actuation: Callable[[MachineEntry], Actuation],
        ensure_can_water: Callable[[str, str], Coroutine[Any, Any, None]],
        is_watering: Callable[[str], bool],
        now: Callable[[], datetime],
        sleep: Callable[[float], Coroutine[Any, Any, None]],
    ) -> None:
        self.actuation = actuation
        self.ensure_can_water = ensure_can_water
        self.is_watering = is_watering
        self.now = now
        self.sleep = sleep


class CalibrationManager:
    def __init__(
        self,
        registry: MachineRegistry,
        store: MachineStore,
        hooks: Hooks,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        tick: float = 0.2,
    ) -> None:
        self._registry = registry
        self._store = store
        self._hooks = hooks
        self._monotonic = monotonic
        self._tick = tick
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self.settings = CalibrationSettings()

    # --- Настройки ---

    async def load(self) -> None:
        raw = await self._store.load_setting(SETTINGS_KEY)
        if raw is not None:
            try:
                self.settings = CalibrationSettings.model_validate_json(raw)
            except Exception:
                log.exception("bad calibration settings, defaults used")

    async def save_settings(self, settings: CalibrationSettings) -> None:
        await self._store.save_setting(SETTINGS_KEY, settings.model_dump_json())
        self.settings = settings

    # --- Сессии ---

    def active_for(self, machine_id: str) -> Session | None:
        for session in self._sessions.values():
            if session.machine_id == machine_id and session.state is not SessionState.CLOSED:
                return session
        return None

    def session(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise UnknownSessionError(f"unknown calibration session {session_id!r}") from None

    async def open(
        self,
        machine_id: str,
        route_id: str,
        method: CalibrationMethod,
        targets: list[float] | None = None,
    ) -> Session:
        entry = self._registry.entry(machine_id)
        if not any(route.id == route_id for route in entry.config.routes):
            raise UnknownRouteError(f"unknown route {route_id!r}")
        if self.active_for(machine_id) is not None:
            raise MachineBusyError(f"machine {machine_id!r} is already being calibrated")
        if self._hooks.is_watering(machine_id):
            raise MachineBusyError(f"machine {machine_id!r} is watering")
        marks: list[float] = []
        if method is CalibrationMethod.MARKS:
            marks = sorted(targets or [])
            if not marks or marks[0] <= 0 or len(set(marks)) != len(marks):
                raise CalibrationError("marks must be positive and distinct")
        session = Session(
            id=uuid.uuid4().hex[:12],
            machine_id=machine_id,
            route_id=route_id,
            method=method,
            targets=marks,
            created_at=self._hooks.now(),
            last_heartbeat=self._monotonic(),
        )
        self._sessions[session.id] = session
        self._spawn_watch(session)
        return session

    def heartbeat(self, session_id: str) -> Session:
        session = self._live(session_id)
        session.last_heartbeat = self._monotonic()
        return session

    async def start_marks_run(self, session_id: str) -> Session:
        session = self._live(session_id)
        if session.method is not CalibrationMethod.MARKS:
            raise CalibrationSessionError("this session runs by time")
        await self._start_run(session, planned_s=None)
        return session

    async def start_timed_run(self, session_id: str, duration_s: float) -> Session:
        session = self._live(session_id)
        if session.method is not CalibrationMethod.TIMED:
            raise CalibrationSessionError("this session runs by marks")
        if duration_s <= 0:
            raise CalibrationError("duration must be positive")
        await self._start_run(session, planned_s=duration_s)
        session.run_task = asyncio.create_task(self._timer(session, duration_s))
        return session

    async def mark(self, session_id: str, t_s: float, volume_ml: float) -> Session:
        """Метка прогона. volume_ml = 0 - вода пошла."""
        session = self._live(session_id)
        run = session.current
        if session.state is not SessionState.RUNNING or run is None:
            raise CalibrationSessionError("no run in progress")
        if session.method is not CalibrationMethod.MARKS:
            raise CalibrationSessionError("this session runs by time")
        last_t = max([t for t, _ in run.marks] + [run.water_started_s or 0.0])
        if t_s <= last_t:
            raise CalibrationError("marks must go forward in time")
        session.last_heartbeat = self._monotonic()

        if volume_ml == 0:
            if run.marks or run.water_started_s is not None:
                raise CalibrationSessionError("water has already started")
            run.water_started_s = t_s
            return session

        expected = (
            session.targets[len(run.marks)] if len(run.marks) < len(session.targets) else None
        )
        if expected is None or abs(volume_ml - expected) > 1e-6:
            raise CalibrationSessionError(f"next mark is {expected} ml")
        run.marks.append((t_s, volume_ml))

        if len(run.marks) == len(session.targets):
            await self._stop(session, StopReason.LAST_MARK, after_s=t_s)
        elif len(run.marks) == 1:
            # Оценка времени до последней метки: пропорция без учёта задержки,
            # она даёт время с запасом.
            total = t_s * session.targets[-1] / volume_ml
            allowed = max(total * self.settings.overtime_factor, t_s + 5)
            session.deadline = session.run_started + allowed
        return session

    async def stop(self, session_id: str) -> Session:
        """Кнопка "Стоп": насос выключается, прогон в расчёт не идёт."""
        session = self._live(session_id)
        if session.state is SessionState.RUNNING:
            await self._stop(session, StopReason.USER)
        return session

    async def submit_volume(self, session_id: str, volume_ml: float) -> Session:
        """Объём в ёмкости после прогона. Для прерванного прогона - только списать воду."""
        session = self._live(session_id)
        run = session.current
        if session.state is not SessionState.AWAITING_VOLUME or run is None:
            raise CalibrationSessionError("no run waits for a volume")
        if volume_ml < 0:
            raise CalibrationError("volume must be non-negative")
        if run.stop_reason is not None and run.stop_reason.completes_run:
            try:
                if session.method is CalibrationMethod.MARKS:
                    run.result = evaluate_marks_run(
                        run.marks,
                        volume_ml,
                        run.water_started_s,
                        self.settings.thresholds(),
                    )
                    if not run.supply_filled and run.supply_ml > 0:
                        run.result = _without_supply(run.result, run.supply_ml)
                elif volume_ml <= 0:
                    raise CalibrationError("volume must be positive")
            except CalibrationError as error:
                run.error = str(error)
        run.volume_ml = volume_ml

        entry = self._registry.entry(session.machine_id)
        entry.machine.record_calibration_run(volume_ml)
        await self._registry.save(entry.machine)
        session.tank_volume_end_ml = entry.machine.tank.volume_ml
        session.state = SessionState.READY
        return session

    async def skip_volume(self, session_id: str) -> Session:
        """Прерванный прогон, объём не мерили: воду не списываем."""
        session = self._live(session_id)
        run = session.current
        if session.state is not SessionState.AWAITING_VOLUME or run is None:
            raise CalibrationSessionError("no run waits for a volume")
        if run.stop_reason is not None and run.stop_reason.completes_run:
            raise CalibrationSessionError("a finished run needs its volume")
        session.state = SessionState.READY
        return session

    def exclude_run(self, session_id: str, index: int, excluded: bool) -> Session:
        session = self._live(session_id)
        for run in session.runs:
            if run.index == index:
                run.excluded = excluded
                return session
        raise CalibrationSessionError(f"no run {index}")

    async def close(self, session_id: str) -> None:
        """Отмена мастера: выключить насос, закрыть сессию."""
        session = self.session(session_id)
        if session.state is SessionState.RUNNING:
            await self._stop(session, StopReason.USER)
        session.state = SessionState.CLOSED
        self._sessions.pop(session.id, None)

    async def abort_machine(self, machine_id: str) -> None:
        """Аварийный стоп машины: калибровка прерывается вместе с поливом."""
        session = self.active_for(machine_id)
        if session is not None:
            await self.close(session.id)

    async def shutdown(self) -> None:
        for session in list(self._sessions.values()):
            with contextlib.suppress(Exception):
                await self.close(session.id)

    def elapsed_s(self, session: Session) -> float | None:
        if session.state is not SessionState.RUNNING:
            return None
        return self._monotonic() - session.run_started

    def deadline_in_s(self, session: Session) -> float | None:
        """Через сколько секунд автостоп: по ожиданию метки или по пределу насоса."""
        if session.state is not SessionState.RUNNING:
            return None
        now = self._monotonic()
        entry = self._registry.entry(session.machine_id)
        limit = session.run_started + run_limit_s(entry)
        deadline = min(limit, session.deadline) if session.deadline is not None else limit
        return max(0.0, deadline - now)

    async def history(self, machine_id: str) -> list[StoredCalibration]:
        return await self._store.load_calibrations(machine_id)

    # --- Сохранение ---

    async def save(
        self,
        session_id: str,
        mode: Literal["replace", "second_level"] = "replace",
        make_base: bool = False,
    ) -> RouteCalibrationConfig:
        session = self._live(session_id)
        if session.state is not SessionState.READY:
            raise CalibrationSessionError("finish the current run first")
        result = session.result(self.settings.thresholds())
        reference = session.reference_volume_ml()
        entry = self._registry.entry(session.machine_id)
        config = entry.config.model_copy(deep=True)
        route = config.route(session.route_id)

        points = [FlowPointConfig(tank_volume_ml=reference, flow_ml_s=result.flow_ml_s)]
        prime_s = result.prime_s
        afterflow = result.afterflow_ml
        if mode == "second_level":
            old = route.calibration
            if old is None:
                raise CalibrationError("route has no calibration to add a level to")
            if route.id in entry.stale_routes:
                raise CalibrationError("calibration of the route is stale, replace it")
            first = old.flow_points[0]
            capacity = entry.machine.tank.geometry.capacity_ml()
            gap = abs(first.tank_volume_ml - reference) / capacity * 100
            if gap < self.settings.second_level_min_pct:
                raise CalibrationError(
                    f"tank volumes differ by {gap:.0f}%, "
                    f"need at least {self.settings.second_level_min_pct:.0f}%"
                )
            # Проверка, что две точки дают допустимый профиль.
            old.profile().with_second_level(FlowPoint(reference, result.flow_ml_s))
            points = [first, points[0]]
            prime_s = (old.prime_s + prime_s) / 2
            afterflow = (old.afterflow_ml + afterflow) / 2

        data = {
            "method": session.method.value,
            "targets": session.targets,
            "mode": mode,
            "tank_volume_ml": reference,
            "route_tube_ml": tube_volume_ml(route.connection),
            "runs": [run.to_json() for run in session.runs],
            "result": result_json(result),
        }
        record_id = await self._store.save_calibration(
            session.machine_id, session.route_id, session.method.value, json.dumps(data)
        )
        calibration = RouteCalibrationConfig(
            flow_points=points,
            prime_s=prime_s,
            afterflow_ml=afterflow,
            method=session.method.value,
            calibrated_at=self._hooks.now(),
            spread_pct=result.spread_pct,
            record_id=record_id,
        )
        route.calibration = calibration
        # Откалибровали - значит, хотят поливать по калибровке.
        config.flow_mode = "calibrated"
        if make_base or config.base_route is None:
            config.base_route = route.id
        session.state = SessionState.CLOSED
        self._sessions.pop(session.id, None)
        await self._registry.update(session.machine_id, config)
        return calibration

    # --- Внутреннее ---

    def _live(self, session_id: str) -> Session:
        session = self.session(session_id)
        if session.state is SessionState.CLOSED:
            raise CalibrationSessionError("session is closed")
        return session

    async def _start_run(self, session: Session, planned_s: float | None) -> None:
        async with self._lock:
            if session.state is not SessionState.READY:
                raise CalibrationSessionError("previous run is not finished")
            entry = self._registry.entry(session.machine_id)
            await self._hooks.ensure_can_water(session.machine_id, session.route_id)
            pump = entry.machine.pump
            now = self._hooks.now()
            limit = timedelta(seconds=run_limit_s(entry))
            duration = timedelta(seconds=planned_s) if planned_s is not None else limit
            if planned_s is not None and duration > limit:
                raise PumpRuntimeExceededError(
                    f"run of {planned_s:.0f} s is longer than the pump limit "
                    f"{limit.total_seconds():.0f} s"
                )
            pump.check_can_start(now, duration)

            plumbing = entry.config.plumbing
            supply_ml = (
                tube_volume_ml(plumbing.supply)
                if isinstance(plumbing, CollectorPlumbingConfig)
                else 0.0
            )
            run = Run(
                index=len(session.runs) + 1,
                started_at=now,
                tank_volume_ml=entry.machine.tank.volume_ml,
                supply_filled=entry.machine.supply_is_filled,
                supply_ml=supply_ml,
                planned_s=planned_s,
            )
            actuation = self._hooks.actuation(entry)
            valve_id = entry.machine.valve_for(session.route_id)
            try:
                if valve_id is not None:
                    assert entry.machine.collector is not None
                    await actuation.open_valve(entry.machine.collector, valve_id)
                    await self._hooks.sleep(entry.setup.timings.valve_lead_s)
                await actuation.start_pump(pump)
            except Exception:
                await self._shut_down(entry, session.route_id)
                await self._registry.save(entry.machine)
                raise
            await self._registry.save(entry.machine)
            session.runs.append(run)
            session.state = SessionState.RUNNING
            session.run_started = self._monotonic()
            session.last_heartbeat = session.run_started
            session.deadline = None

    async def _stop(
        self, session: Session, reason: StopReason, after_s: float | None = None
    ) -> None:
        run = session.current
        if session.state is not SessionState.RUNNING or run is None:
            return
        # Сразу меняем состояние: второй стоп (таймер и кнопка разом) ничего не сделает.
        session.state = SessionState.AWAITING_VOLUME
        run.stop_reason = reason
        run.stopped_after_s = (
            after_s if after_s is not None else self._monotonic() - session.run_started
        )
        session.deadline = None
        task = session.run_task
        session.run_task = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
        entry = self._registry.entry(session.machine_id)
        errors = await self._shut_down(entry, session.route_id)
        await self._registry.save(entry.machine)
        if errors:
            run.error = "; ".join(str(error) for error in errors)
            log.error("calibration %s: cannot stop: %s", session.id, run.error)
        if not reason.completes_run:
            log.warning("calibration %s run %d stopped: %s", session.id, run.index, reason.value)

    async def _shut_down(self, entry: MachineEntry, route_id: str) -> list[Exception]:
        actuation = self._hooks.actuation(entry)
        errors: list[Exception] = []
        pump_error = await actuation.stop_pump(entry.machine.pump)
        if pump_error is not None:
            errors.append(pump_error)
        collector = entry.machine.collector
        valve_id = entry.machine.valve_for(route_id)
        if valve_id is not None and collector is not None:
            if collector.valve_state(valve_id) is not ValveState.CLOSED:
                await self._hooks.sleep(entry.setup.timings.valve_lag_s)
            valve_error = await actuation.close_valve(collector, valve_id)
            if valve_error is not None:
                errors.append(valve_error)
        return errors

    async def _timer(self, session: Session, duration_s: float) -> None:
        await self._hooks.sleep(duration_s)
        await self._stop(session, StopReason.TIMER, after_s=duration_s)

    def _spawn_watch(self, session: Session) -> None:
        task = asyncio.create_task(self._watch(session))
        # Держим ссылку, иначе задачу может собрать сборщик мусора.
        _watchers.add(task)
        task.add_done_callback(_watchers.discard)

    async def _watch(self, session: Session) -> None:
        """Сторож сессии: автостоп прогона и закрытие брошенной сессии."""
        while session.state is not SessionState.CLOSED:
            await asyncio.sleep(self._tick)
            try:
                await self._check(session)
            except Exception:
                log.exception("calibration watch failed for %s", session.id)

    async def _check(self, session: Session) -> None:
        now = self._monotonic()
        silent = now - session.last_heartbeat
        if session.state is SessionState.RUNNING:
            entry = self._registry.entry(session.machine_id)
            limit = run_limit_s(entry)
            if silent > self.settings.heartbeat_timeout_s:
                await self._stop(session, StopReason.HEARTBEAT)
            elif session.deadline is not None and now > session.deadline:
                await self._stop(session, StopReason.OVERTIME)
            elif now - session.run_started > limit:
                await self._stop(session, StopReason.MAX_RUNTIME)
        elif silent > self.settings.idle_timeout_s:
            log.info("calibration %s abandoned, closed", session.id)
            await self.close(session.id)


_watchers: set[asyncio.Task[None]] = set()

# Предел прогона калибровки, если у насоса предел работы выключен.
# Замер дольше 10 минут не нужен, а насос без присмотра оставлять нельзя.
UNLIMITED_PUMP_RUN_S = 600.0


def run_limit_s(entry: MachineEntry) -> float:
    limit = entry.machine.pump.passport.max_runtime
    return UNLIMITED_PUMP_RUN_S if limit is None else limit.total_seconds()


def _without_supply(result: RunResult, supply_ml: float) -> RunResult:
    """Прогон начался с пустой трубкой до коллектора: её заполнение не входит в задержку.

    При поливе пустая трубка учитывается отдельно (CollectorPlumbing).
    """
    return replace(result, prime_s=max(0.0, result.prime_s - supply_ml / result.flow_ml_s))
