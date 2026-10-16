"""REST API экспорта и импорта поливальных машин."""

from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel

from plant_control_addon.api.machines import Control, MachineOut, Registry, machine_out
from plant_control_addon.transfer import ExportBundle, ImportPlan

router = APIRouter(tags=["transfer"])


class ImportRequest(BaseModel):
    bundle: ExportBundle
    # id машин из файла. None - все.
    machines: list[str] | None = None


@router.get("/api/export")
async def export_machines(
    registry: Registry, machines: Annotated[list[str] | None, Query()] = None
) -> ExportBundle:
    """Машины с оборудованием и расписаниями одним файлом. Без machines - все."""
    return registry.export(machines)


@router.post("/api/import/preview")
async def preview_import(bundle: ExportBundle, registry: Registry) -> ImportPlan:
    """Что будет при импорте: какие машины, какие реле уже заняты. Ничего не меняет."""
    return registry.plan_import(bundle)


@router.post("/api/import", status_code=status.HTTP_201_CREATED)
async def import_machines(
    body: ImportRequest, registry: Registry, control: Control
) -> list[MachineOut]:
    created = await registry.import_bundle(body.bundle, body.machines)
    for entry in created:
        await control.safe_start(entry.id)
    await control.recheck()
    return [machine_out(entry, control) for entry in created]
