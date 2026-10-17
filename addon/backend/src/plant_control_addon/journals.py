"""Журналы: поливы, калибровки, проблемы. Очистка и срок хранения.

Журнал поливов живёт в базе и в памяти очереди, чистится в обоих местах.
Калибровка, из которой взяты действующие параметры растения, не удаляется:
по ней видно, откуда эти параметры. Журнал проблем пишется здесь: когда
проблема открылась и когда закрылась.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from plant_control.application.health import HealthReport
from plant_control.application.queue import RequestState, WateringQueue

from plant_control_addon.registry import MachineRegistry, UnknownMachineError
from plant_control_addon.storage import MachineStore, NewProblemLog, ProblemLogRecord

log = logging.getLogger(__name__)

SETTINGS_KEY = "journals"
# Как часто убирать записи старше срока хранения.
PRUNE_EVERY = timedelta(hours=6)
# Состояния поливов, которые считаются удачными: остальное попадает в фильтр "Проблемы".
FINE_STATES = frozenset({RequestState.DONE.value, RequestState.CANCELLED.value})

WateringScope = Literal["all", "problems"]


@dataclass(frozen=True, slots=True)
class JournalSettings:
    # Сколько дней хранить записи. None - не ограничивать (остаётся предел по числу записей).
    keep_days: int | None = None


class Journals:
    def __init__(
        self,
        store: MachineStore,
        registry: MachineRegistry,
        queue: WateringQueue,
        now: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._registry = registry
        self._queue = queue
        self._now = now
        self._settings = JournalSettings()
        # Записи о проблемах пишутся по порядку: закрытие не обгонит открытие.
        self._lock = asyncio.Lock()

    @property
    def settings(self) -> JournalSettings:
        return self._settings

    async def load(self) -> None:
        raw = await self._store.load_setting(SETTINGS_KEY)
        if raw:
            data = json.loads(raw)
            self._settings = JournalSettings(keep_days=data.get("keep_days"))
        # Проблемы, открытые до перезапуска, закрываются: живые откроются заново.
        await self._store.close_all_problem_log(self._now())

    async def save_settings(self, settings: JournalSettings) -> None:
        self._settings = settings
        await self._store.save_setting(SETTINGS_KEY, json.dumps({"keep_days": settings.keep_days}))
        await self.prune()

    # --- Поливы ---

    async def clear_waterings(
        self,
        scope: WateringScope = "all",
        older_than_days: int | None = None,
        ids: Collection[str] | None = None,
    ) -> int:
        """Удалить законченные поливы. Сколько записей удалено."""
        cutoff = self._cutoff(older_than_days)
        wanted = set(ids) if ids is not None else None
        chosen = [
            record_id
            for record_id, state, at in await self._store.watering_times()
            if (wanted is None or record_id in wanted)
            and (scope == "all" or state not in FINE_STATES)
            and (cutoff is None or at < cutoff)
        ]
        # В памяти очереди могут быть записи, которых ещё нет в базе.
        for request in self._queue.history():
            if request.id in chosen:
                continue
            at = request.finished_at or request.requested_at
            if (
                (wanted is None or request.id in wanted)
                and (scope == "all" or request.state.value not in FINE_STATES)
                and (cutoff is None or at < cutoff)
            ):
                chosen.append(request.id)
        in_memory = self._queue.forget(chosen)
        in_store = await self._store.delete_waterings(chosen)
        return max(in_memory, in_store)

    # --- Калибровки ---

    def active_calibrations(self) -> set[int]:
        """Записи, из которых взяты действующие параметры растений (у любой машины)."""
        active: set[int] = set()
        for entry in self._registry.entries():
            for route in entry.config.routes:
                record_id = route.calibration.record_id if route.calibration else None
                if record_id is not None:
                    active.add(record_id)
        return active

    async def clear_calibrations(
        self,
        machine_id: str | None,
        older_than_days: int | None = None,
        ids: Collection[int] | None = None,
    ) -> int:
        cutoff = self._cutoff(older_than_days)
        keep = self.active_calibrations()
        wanted = set(ids) if ids is not None else None
        chosen = [
            record_id
            for record_id, at in await self._store.calibration_times(machine_id)
            if record_id not in keep
            and (wanted is None or record_id in wanted)
            and (cutoff is None or at < cutoff)
        ]
        return await self._store.delete_calibrations(chosen)

    # --- Проблемы ---

    async def record(self, report: HealthReport) -> None:
        """Записать в журнал открытые и закрытые проверкой проблемы."""
        if not report.opened and not report.closed:
            return
        async with self._lock:
            try:
                if report.opened:
                    await self._store.open_problem_log(
                        [
                            NewProblemLog(
                                machine_id=p.machine_id,
                                machine_name=self._machine_name(p.machine_id),
                                kind=p.kind.value,
                                target=p.target,
                                details=p.details,
                                blocking=p.blocking,
                                opened_at=p.opened_at,
                            )
                            for p in report.opened
                        ]
                    )
                if report.closed:
                    await self._store.close_problem_log(
                        [(p.machine_id, p.kind.value, p.target) for p in report.closed],
                        self._now(),
                    )
            except Exception:
                log.exception("cannot write problem journal")

    async def problem_log(self, limit: int = 500) -> list[ProblemLogRecord]:
        return await self._store.load_problem_log(limit)

    async def clear_problems(
        self, older_than_days: int | None = None, ids: Collection[int] | None = None
    ) -> int:
        """Удалить закрытые проблемы. Открытые остаются: они ещё идут."""
        cutoff = self._cutoff(older_than_days)
        wanted = set(ids) if ids is not None else None
        chosen = [
            r.id
            for r in await self._store.load_problem_log(1_000_000)
            if r.closed_at is not None
            and (wanted is None or r.id in wanted)
            and (cutoff is None or r.closed_at < cutoff)
        ]
        return await self._store.delete_problem_log(chosen)

    # --- Срок хранения ---

    async def prune(self) -> None:
        days = self._settings.keep_days
        if days is None:
            return
        waterings = await self.clear_waterings(older_than_days=days)
        calibrations = await self.clear_calibrations(None, older_than_days=days)
        problems = await self.clear_problems(older_than_days=days)
        if waterings or calibrations or problems:
            log.info(
                "journals pruned: %d waterings, %d calibrations, %d problems",
                waterings,
                calibrations,
                problems,
            )

    async def prune_loop(self) -> None:
        while True:
            try:
                await self.prune()
            except Exception:
                log.exception("journal pruning failed")
            await asyncio.sleep(PRUNE_EVERY.total_seconds())

    def _cutoff(self, days: int | None) -> datetime | None:
        return self._now() - timedelta(days=days) if days is not None else None

    def _machine_name(self, machine_id: str) -> str:
        try:
            return self._registry.entry(machine_id).config.name
        except UnknownMachineError:
            return machine_id
