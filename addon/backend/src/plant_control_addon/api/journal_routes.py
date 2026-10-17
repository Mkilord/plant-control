"""REST API журналов: очистка поливов, калибровок и проблем, срок хранения."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from plant_control_addon.journals import Journals, JournalSettings
from plant_control_addon.registry import MachineRegistry


def get_journals(request: Request) -> Journals:
    journals: Journals = request.app.state.journals
    return journals


def get_registry(request: Request) -> MachineRegistry:
    registry: MachineRegistry = request.app.state.registry
    return registry


JournalsDep = Annotated[Journals, Depends(get_journals)]
Registry = Annotated[MachineRegistry, Depends(get_registry)]

router = APIRouter(prefix="/api/journals", tags=["journals"])


class SettingsIO(BaseModel):
    # Сколько дней хранить записи журналов. Пусто - не ограничивать.
    keep_days: int | None = Field(default=None, ge=1, le=3650)


class ClearWaterings(BaseModel):
    # problems - только неудачные: ошибка, пропуск, не дождались очереди.
    scope: Literal["all", "problems"] = "all"
    older_than_days: int | None = Field(default=None, ge=0)
    ids: list[str] | None = None


class ClearCalibrations(BaseModel):
    machine_id: str
    older_than_days: int | None = Field(default=None, ge=0)
    ids: list[int] | None = None


class ClearProblems(BaseModel):
    older_than_days: int | None = Field(default=None, ge=0)
    ids: list[int] | None = None


class Cleared(BaseModel):
    deleted: int


class ProblemLogOut(BaseModel):
    id: int
    machine_id: str
    machine_name: str
    kind: str
    target: str
    details: str
    blocking: bool
    opened_at: datetime
    closed_at: datetime | None


@router.get("/settings")
async def show_settings(journals: JournalsDep) -> SettingsIO:
    return SettingsIO(keep_days=journals.settings.keep_days)


@router.put("/settings")
async def save_settings(body: SettingsIO, journals: JournalsDep) -> SettingsIO:
    await journals.save_settings(JournalSettings(keep_days=body.keep_days))
    return body


@router.post("/waterings/clear")
async def clear_waterings(body: ClearWaterings, journals: JournalsDep) -> Cleared:
    deleted = await journals.clear_waterings(body.scope, body.older_than_days, body.ids)
    return Cleared(deleted=deleted)


@router.post("/calibrations/clear")
async def clear_calibrations(
    body: ClearCalibrations, journals: JournalsDep, registry: Registry
) -> Cleared:
    """Действующие калибровки не удаляются никогда."""
    registry.entry(body.machine_id)
    deleted = await journals.clear_calibrations(body.machine_id, body.older_than_days, body.ids)
    return Cleared(deleted=deleted)


@router.get("/problems")
async def problem_log(journals: JournalsDep, registry: Registry) -> list[ProblemLogOut]:
    names = {entry.id: entry.config.name for entry in registry.entries()}
    return [
        ProblemLogOut(
            id=r.id,
            machine_id=r.machine_id,
            # Машину могли переименовать: показываем текущее имя, если она ещё есть.
            machine_name=names.get(r.machine_id, r.machine_name),
            kind=r.kind,
            target=r.target,
            details=r.details,
            blocking=r.blocking,
            opened_at=r.opened_at,
            closed_at=r.closed_at,
        )
        for r in await journals.problem_log()
    ]


@router.post("/problems/clear")
async def clear_problems(body: ClearProblems, journals: JournalsDep) -> Cleared:
    """Открытые проблемы не удаляются: они ещё идут."""
    deleted = await journals.clear_problems(body.older_than_days, body.ids)
    return Cleared(deleted=deleted)
