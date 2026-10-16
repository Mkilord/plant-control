"""REST API справочников: баки, насосы, коллекторы, расписания, группы питания."""

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from plant_control_addon.api.machines import Control, Registry
from plant_control_addon.catalog import CatalogItem, CatalogKind, parse_item
from plant_control_addon.registry import MachineEntry, MachineRegistry

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


class UserOut(BaseModel):
    """Машина, которая использует запись. routes - растения, если запись про растение."""

    machine_id: str
    name: str
    routes: list[str] = []


class ItemOut(BaseModel):
    id: str
    kind: CatalogKind
    item: dict[str, Any]
    users: list[UserOut]


class ImpactOut(BaseModel):
    """Что затронет сохранение записи."""

    machine_id: str
    name: str
    # Маршруты, у которых калибровка станет устаревшей.
    stale_routes: list[str]


def _users(registry: MachineRegistry, kind: CatalogKind, item_id: str) -> list[UserOut]:
    result = []
    for entry in registry.users(kind, item_id):
        routes = (
            [
                r.id
                for r in entry.config.routes
                if r.schedule_link is not None and r.schedule_link.template == item_id
            ]
            if kind == "schedule"
            else []
        )
        result.append(UserOut(machine_id=entry.id, name=entry.config.name, routes=routes))
    return result


def item_out(
    registry: MachineRegistry, kind: CatalogKind, item_id: str, item: CatalogItem
) -> ItemOut:
    return ItemOut(
        id=item_id,
        kind=kind,
        item=item.model_dump(mode="json"),
        users=_users(registry, kind, item_id),
    )


@router.get("")
async def list_all(registry: Registry) -> dict[CatalogKind, list[ItemOut]]:
    """Все справочники разом: интерфейсу они нужны почти на каждом экране."""
    kinds: tuple[CatalogKind, ...] = ("tank", "pump", "collector", "schedule", "power")
    return {
        kind: [
            item_out(registry, kind, item_id, item)
            for item_id, item in registry.catalog.items(kind).items()
        ]
        for kind in kinds
    }


@router.get("/{kind}")
async def list_items(kind: CatalogKind, registry: Registry) -> list[ItemOut]:
    return [
        item_out(registry, kind, item_id, item)
        for item_id, item in registry.catalog.items(kind).items()
    ]


@router.get("/{kind}/{item_id}")
async def get_item(kind: CatalogKind, item_id: str, registry: Registry) -> ItemOut:
    return item_out(registry, kind, item_id, registry.catalog.get(kind, item_id))


@router.post("/{kind}", status_code=status.HTTP_201_CREATED)
async def create_item(kind: CatalogKind, body: dict[str, Any], registry: Registry) -> ItemOut:
    item = parse_item(kind, body)
    item_id = await registry.create_item(kind, item)
    return item_out(registry, kind, item_id, item)


@router.post("/{kind}/{item_id}/preview")
async def preview_item(
    kind: CatalogKind, item_id: str, body: dict[str, Any], registry: Registry
) -> list[ImpactOut]:
    """Какие машины затронет изменение и у каких устареет калибровка. Ничего не меняет."""
    item = parse_item(kind, body)
    return [
        ImpactOut(machine_id=entry.id, name=entry.config.name, stale_routes=sorted(stale))
        for entry, stale in registry.preview_item(kind, item_id, item)
    ]


@router.put("/{kind}/{item_id}")
async def update_item(
    kind: CatalogKind, item_id: str, body: dict[str, Any], registry: Registry, control: Control
) -> ItemOut:
    item = parse_item(kind, body)
    rebuilt = await registry.update_item(kind, item_id, item, is_busy=control.is_busy)
    await _recheck(control, rebuilt)
    return item_out(registry, kind, item_id, item)


@router.delete("/{kind}/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(kind: CatalogKind, item_id: str, registry: Registry) -> None:
    await registry.delete_item(kind, item_id)


async def _recheck(control: Control, rebuilt: list[MachineEntry]) -> None:
    """Калибровка могла устареть: показать это в проблемах сразу."""
    if rebuilt:
        await control.recheck()
