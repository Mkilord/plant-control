"""Хранилище машин и настроек в SQLite.

Машины: id, конфигурация (JSON), состояние (JSON). Машина - агрегат,
поэтому хранится целиком, без разбора на таблицы.
Настройки: ключ и значение (JSON), например настройки уведомлений.
Журнал поливов: завершённые заявки, чтобы история переживала перезапуск.
Журнал калибровок: все прогоны и точки замера, а не только итог.
Справочники: вид записи, id, конфигурация (JSON).

sqlite3 из стандартной библиотеки синхронный, поэтому каждый запрос уходит
в отдельный поток через asyncio.to_thread, чтобы не блокировать цикл событий.
"""

import asyncio
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from plant_control.application.queue import RequestSource, RequestState, WateringRequest

from plant_control_addon.config import MachineConfig, MachineState

SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    id TEXT PRIMARY KEY,
    config TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

WATERINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS waterings (
    id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    dose_ml REAL NOT NULL,
    source TEXT NOT NULL,
    state TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error TEXT
)
"""

# Сколько записей журнала хранить в базе. Старше - удаляются.
WATERINGS_KEEP = 1000

SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


CALIBRATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS calibrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
)
"""

PROBLEM_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS problem_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id TEXT NOT NULL,
    machine_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    details TEXT NOT NULL,
    blocking INTEGER NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT
)
"""

# Сколько записей журнала проблем хранить. Старше - удаляются.
PROBLEM_LOG_KEEP = 500

CATALOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog (
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    config TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, id)
)
"""


@dataclass(frozen=True, slots=True)
class StoredCatalogItem:
    kind: str
    id: str
    config_json: str


@dataclass(frozen=True, slots=True)
class StoredCalibration:
    id: int
    machine_id: str
    route_id: str
    method: str
    created_at: datetime
    data_json: str


@dataclass(frozen=True, slots=True)
class ProblemLogRecord:
    id: int
    machine_id: str
    machine_name: str
    kind: str
    target: str
    details: str
    blocking: bool
    opened_at: datetime
    closed_at: datetime | None


@dataclass(frozen=True, slots=True)
class NewProblemLog:
    machine_id: str
    machine_name: str
    kind: str
    target: str
    details: str
    blocking: bool
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class StoredMachine:
    id: str
    config_json: str
    state_json: str


class MachineStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def open(self) -> None:
        await asyncio.to_thread(self._open)

    async def load_all(self) -> list[StoredMachine]:
        return await asyncio.to_thread(self._load_all)

    async def upsert(self, machine_id: str, config: MachineConfig, state: MachineState) -> None:
        await asyncio.to_thread(
            self._upsert, machine_id, config.model_dump_json(), state.model_dump_json()
        )

    async def save_state(self, machine_id: str, state: MachineState) -> None:
        await asyncio.to_thread(self._save_state, machine_id, state.model_dump_json())

    async def delete(self, machine_id: str) -> None:
        await asyncio.to_thread(self._delete, machine_id)

    async def save_watering(self, request: WateringRequest) -> None:
        await asyncio.to_thread(self._save_watering, request)

    async def load_waterings(self, limit: int) -> list[WateringRequest]:
        """Последние записи журнала, сначала новые."""
        return await asyncio.to_thread(self._load_waterings, limit)

    async def save_calibration(
        self, machine_id: str, route_id: str, method: str, data_json: str
    ) -> int:
        """Записать калибровку в журнал. Возвращает id записи."""
        return await asyncio.to_thread(
            self._save_calibration, machine_id, route_id, method, data_json
        )

    async def load_calibrations(self, machine_id: str, limit: int = 50) -> list[StoredCalibration]:
        """Калибровки машины, сначала новые."""
        return await asyncio.to_thread(self._load_calibrations, machine_id, limit)

    async def delete_waterings(self, ids: Collection[str]) -> int:
        """Удалить записи журнала поливов. Идущие и ждущие заявки не трогаются."""
        return await asyncio.to_thread(self._delete_waterings, list(ids))

    async def watering_times(self) -> list[tuple[str, str, datetime]]:
        """Все законченные записи журнала: id, состояние, время."""
        return await asyncio.to_thread(self._watering_times)

    async def delete_calibrations(self, ids: Collection[int]) -> int:
        return await asyncio.to_thread(self._delete_calibrations, list(ids))

    async def calibration_times(self, machine_id: str | None) -> list[tuple[int, datetime]]:
        """id и время калибровок машины (или всех машин)."""
        return await asyncio.to_thread(self._calibration_times, machine_id)

    async def open_problem_log(self, records: Collection[NewProblemLog]) -> None:
        await asyncio.to_thread(self._open_problem_log, list(records))

    async def close_problem_log(
        self, keys: Collection[tuple[str, str, str]], closed_at: datetime
    ) -> None:
        """Отметить конец открытых записей по ключу (машина, вид, цель)."""
        await asyncio.to_thread(self._close_problem_log, list(keys), closed_at)

    async def close_all_problem_log(self, closed_at: datetime) -> None:
        """Перезапуск: что было открыто, закрывается. Живые проблемы откроются заново."""
        await asyncio.to_thread(self._close_problem_log, None, closed_at)

    async def load_problem_log(self, limit: int) -> list[ProblemLogRecord]:
        """Журнал проблем, сначала новые."""
        return await asyncio.to_thread(self._load_problem_log, limit)

    async def delete_problem_log(self, ids: Collection[int]) -> int:
        return await asyncio.to_thread(self._delete_problem_log, list(ids))

    async def journal_machine_ids(self) -> set[str]:
        """Машины, упомянутые в журналах, в том числе уже удалённые."""
        return await asyncio.to_thread(self._journal_machine_ids)

    async def load_catalog(self) -> list[StoredCatalogItem]:
        return await asyncio.to_thread(self._load_catalog)

    async def save_catalog_item(self, kind: str, item_id: str, config_json: str) -> None:
        await asyncio.to_thread(self._save_catalog_items, [(kind, item_id, config_json)])

    async def delete_catalog_item(self, kind: str, item_id: str) -> None:
        await asyncio.to_thread(self._delete_catalog_item, kind, item_id)

    async def apply_migration(
        self, items: list[tuple[str, str, str]], machines: dict[str, str]
    ) -> None:
        """Записи справочников и переписанные машины одной транзакцией."""
        await asyncio.to_thread(self._apply_migration, items, machines)

    async def load_setting(self, key: str) -> str | None:
        """JSON настройки или None, если её ещё не сохраняли."""
        return await asyncio.to_thread(self._load_setting, key)

    async def save_setting(self, key: str, value_json: str) -> None:
        await asyncio.to_thread(self._save_setting, key, value_json)

    # --- Синхронная часть, выполняется в потоке ---

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def _open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # with для соединения sqlite3 - это транзакция: commit при выходе, rollback при ошибке.
        with self._connect() as db:
            db.execute(SCHEMA)
            db.execute(SETTINGS_SCHEMA)
            db.execute(WATERINGS_SCHEMA)
            db.execute(CALIBRATIONS_SCHEMA)
            db.execute(CATALOG_SCHEMA)
            db.execute(PROBLEM_LOG_SCHEMA)

    def _load_all(self) -> list[StoredMachine]:
        with self._connect() as db:
            rows = db.execute("SELECT id, config, state FROM machines ORDER BY created_at")
            return [StoredMachine(*row) for row in rows]

    def _upsert(self, machine_id: str, config: str, state: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO machines (id, config, state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    config = excluded.config,
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (machine_id, config, state, now, now),
            )

    def _save_state(self, machine_id: str, state: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute(
                "UPDATE machines SET state = ?, updated_at = ? WHERE id = ?",
                (state, now, machine_id),
            )

    def _delete(self, machine_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM machines WHERE id = ?", (machine_id,))

    def _save_calibration(self, machine_id: str, route_id: str, method: str, data: str) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO calibrations (machine_id, route_id, method, created_at, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (machine_id, route_id, method, now, data),
            )
            return int(cursor.lastrowid or 0)

    def _load_calibrations(self, machine_id: str, limit: int) -> list[StoredCalibration]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, machine_id, route_id, method, created_at, data FROM calibrations
                WHERE machine_id = ? ORDER BY id DESC LIMIT ?
                """,
                (machine_id, limit),
            ).fetchall()
        return [
            StoredCalibration(
                row[0], row[1], row[2], row[3], datetime.fromisoformat(row[4]), row[5]
            )
            for row in rows
        ]

    def _delete_waterings(self, ids: list[str]) -> int:
        with self._connect() as db:
            deleted = 0
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                cursor = db.execute(
                    f"DELETE FROM waterings WHERE id IN ({marks})"  # noqa: S608
                    " AND state NOT IN ('queued', 'running')",
                    chunk,
                )
                deleted += cursor.rowcount
            return deleted

    def _watering_times(self) -> list[tuple[str, str, datetime]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, state, COALESCE(finished_at, requested_at) FROM waterings
                WHERE state NOT IN ('queued', 'running')
                """
            ).fetchall()
        return [(row[0], row[1], datetime.fromisoformat(row[2])) for row in rows]

    def _delete_calibrations(self, ids: list[int]) -> int:
        with self._connect() as db:
            deleted = 0
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                cursor = db.execute(
                    f"DELETE FROM calibrations WHERE id IN ({marks})",  # noqa: S608
                    chunk,
                )
                deleted += cursor.rowcount
            return deleted

    def _calibration_times(self, machine_id: str | None) -> list[tuple[int, datetime]]:
        with self._connect() as db:
            if machine_id is None:
                rows = db.execute("SELECT id, created_at FROM calibrations").fetchall()
            else:
                rows = db.execute(
                    "SELECT id, created_at FROM calibrations WHERE machine_id = ?", (machine_id,)
                ).fetchall()
        return [(row[0], datetime.fromisoformat(row[1])) for row in rows]

    def _open_problem_log(self, records: list[NewProblemLog]) -> None:
        with self._connect() as db:
            db.executemany(
                """
                INSERT INTO problem_log (machine_id, machine_name, kind, target, details,
                    blocking, opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r.machine_id,
                        r.machine_name,
                        r.kind,
                        r.target,
                        r.details,
                        int(r.blocking),
                        r.opened_at.isoformat(),
                    )
                    for r in records
                ],
            )
            db.execute(
                "DELETE FROM problem_log WHERE id NOT IN "
                "(SELECT id FROM problem_log ORDER BY id DESC LIMIT ?)",
                (PROBLEM_LOG_KEEP,),
            )

    def _close_problem_log(
        self, keys: list[tuple[str, str, str]] | None, closed_at: datetime
    ) -> None:
        with self._connect() as db:
            if keys is None:
                db.execute(
                    "UPDATE problem_log SET closed_at = ? WHERE closed_at IS NULL",
                    (closed_at.isoformat(),),
                )
                return
            db.executemany(
                """
                UPDATE problem_log SET closed_at = ?
                WHERE closed_at IS NULL AND machine_id = ? AND kind = ? AND target = ?
                """,
                [(closed_at.isoformat(), *key) for key in keys],
            )

    def _load_problem_log(self, limit: int) -> list[ProblemLogRecord]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, machine_id, machine_name, kind, target, details, blocking,
                    opened_at, closed_at
                FROM problem_log ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            ProblemLogRecord(
                id=row[0],
                machine_id=row[1],
                machine_name=row[2],
                kind=row[3],
                target=row[4],
                details=row[5],
                blocking=bool(row[6]),
                opened_at=datetime.fromisoformat(row[7]),
                closed_at=_parse(row[8]),
            )
            for row in rows
        ]

    def _delete_problem_log(self, ids: list[int]) -> int:
        with self._connect() as db:
            deleted = 0
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                cursor = db.execute(
                    f"DELETE FROM problem_log WHERE id IN ({marks})",  # noqa: S608
                    chunk,
                )
                deleted += cursor.rowcount
            return deleted

    def _journal_machine_ids(self) -> set[str]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT machine_id FROM waterings
                UNION SELECT machine_id FROM calibrations
                UNION SELECT machine_id FROM problem_log
                UNION SELECT id FROM machines
                """
            ).fetchall()
        return {row[0] for row in rows}

    def _load_catalog(self) -> list[StoredCatalogItem]:
        with self._connect() as db:
            rows = db.execute("SELECT kind, id, config FROM catalog ORDER BY created_at, id")
            return [StoredCatalogItem(*row) for row in rows]

    def _save_catalog_items(self, items: list[tuple[str, str, str]]) -> None:
        with self._connect() as db:
            self._write_catalog(db, items)

    @staticmethod
    def _write_catalog(db: sqlite3.Connection, items: list[tuple[str, str, str]]) -> None:
        now = datetime.now(UTC).isoformat()
        for kind, item_id, config in items:
            db.execute(
                """
                INSERT INTO catalog (kind, id, config, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(kind, id) DO UPDATE SET
                    config = excluded.config,
                    updated_at = excluded.updated_at
                """,
                (kind, item_id, config, now, now),
            )

    def _delete_catalog_item(self, kind: str, item_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM catalog WHERE kind = ? AND id = ?", (kind, item_id))

    def _apply_migration(self, items: list[tuple[str, str, str]], machines: dict[str, str]) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            self._write_catalog(db, items)
            for machine_id, config in machines.items():
                db.execute(
                    "UPDATE machines SET config = ?, updated_at = ? WHERE id = ?",
                    (config, now, machine_id),
                )

    def _load_setting(self, key: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return str(row[0]) if row else None

    def _save_setting(self, key: str, value: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def _save_watering(self, r: WateringRequest) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO waterings (id, machine_id, route_id, dose_ml, source,
                    state, requested_at, started_at, finished_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.id,
                    r.machine_id,
                    r.route_id,
                    r.dose_ml,
                    r.source.value,
                    r.state.value,
                    r.requested_at.isoformat(),
                    _iso(r.started_at),
                    _iso(r.finished_at),
                    r.error,
                ),
            )
            db.execute(
                """
                DELETE FROM waterings WHERE id NOT IN (
                    SELECT id FROM waterings ORDER BY COALESCE(finished_at, requested_at) DESC
                    LIMIT ?
                )
                """,
                (WATERINGS_KEEP,),
            )

    def _load_waterings(self, limit: int) -> list[WateringRequest]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, machine_id, route_id, dose_ml, source, state,
                    requested_at, started_at, finished_at, error
                FROM waterings ORDER BY COALESCE(finished_at, requested_at) DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        result: list[WateringRequest] = []
        for row in rows:
            request = WateringRequest(
                id=row[0],
                seq=0,
                machine_id=row[1],
                route_id=row[2],
                dose_ml=row[3],
                source=RequestSource(row[4]),
                requested_at=datetime.fromisoformat(row[6]),
            )
            request.state = RequestState(row[5])
            request.started_at = _parse(row[7])
            request.finished_at = _parse(row[8])
            request.error = row[9]
            result.append(request)
        return result


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _chunks[T](items: list[T], size: int = 500) -> list[list[T]]:
    """Части списка: у SQLite есть предел числа параметров в запросе."""
    return [items[i : i + size] for i in range(0, len(items), size)]
