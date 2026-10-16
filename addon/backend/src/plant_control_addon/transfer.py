"""Экспорт и импорт поливальных машин.

Файл экспорта: машины и только те записи оборудования и расписаний, на которые
они ссылаются. Состояние (вода в баке, насос, клапаны, отметки расписаний) не
переносится: на новом месте его снимут заново.

Импорт:
- запись оборудования, которая уже есть с теми же настройками, переиспользуется,
  остальные создаются;
- калибровки переносятся. Действующая в исходной системе калибровка действует и
  после импорта, устаревшая остаётся устаревшей;
- машина, у которой реле уже занято другой машиной, не импортируется.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from plant_control_addon.assembly import CatalogMismatchError
from plant_control_addon.catalog import KINDS, Catalog, CatalogItem, CatalogKind, parse_item
from plant_control_addon.config import CollectorPlumbingConfig, MachineConfig

FORMAT: Literal["plant-control-machines"] = "plant-control-machines"
# Метка для калибровки, устаревшей ещё в исходной системе: не совпадёт ни с каким отпечатком.
STALE_FINGERPRINT = "stale-on-export"


class ExportedMachine(BaseModel):
    id: str
    config: MachineConfig


class ExportBundle(BaseModel):
    format: Literal["plant-control-machines"] = FORMAT
    version: Literal[1] = 1
    exported_at: datetime
    # Записи справочников по видам: id -> настройки записи.
    catalog: dict[CatalogKind, dict[str, dict[str, object]]] = Field(default_factory=dict)
    machines: list[ExportedMachine]


def referenced(config: MachineConfig) -> list[tuple[CatalogKind, str]]:
    refs: list[tuple[CatalogKind, str]] = [("tank", config.tank_type), ("pump", config.pump.model)]
    if isinstance(config.plumbing, CollectorPlumbingConfig):
        refs.append(("collector", config.plumbing.collector_type))
    if config.power_group is not None:
        refs.append(("power", config.power_group))
    for route in config.routes:
        if route.schedule_link is not None:
            refs.append(("schedule", route.schedule_link.template))
    return refs


def build_export(
    machines: list[tuple[str, MachineConfig, frozenset[str]]], catalog: Catalog
) -> ExportBundle:
    """machines - (id, конфигурация, устаревшие маршруты)."""
    items: dict[CatalogKind, dict[str, dict[str, object]]] = {}
    exported: list[ExportedMachine] = []
    for machine_id, config, stale in machines:
        for kind, item_id in referenced(config):
            item = catalog.get(kind, item_id)
            items.setdefault(kind, {})[item_id] = item.model_dump(mode="json")
        config = config.model_copy(deep=True)
        for route in config.routes:
            if route.calibration is None:
                continue
            # Отпечаток зависит от id записей, а они при импорте другие.
            # Поэтому переносится только признак: действовала калибровка или устарела.
            route.calibration.fingerprint = STALE_FINGERPRINT if route.id in stale else None
        exported.append(ExportedMachine(id=machine_id, config=config))
    return ExportBundle(exported_at=datetime.now(UTC), catalog=items, machines=exported)


class ImportPlanItem(BaseModel):
    """Что будет с машиной при импорте."""

    id: str
    name: str
    plants: int
    # Реле, занятые машинами этой системы: такую машину импортировать нельзя.
    taken: dict[str, str] = Field(default_factory=dict)


class ImportPlan(BaseModel):
    machines: list[ImportPlanItem]
    # Сколько записей оборудования и расписаний будет создано и сколько найдено готовыми.
    new_items: int
    reused_items: int


def match_items(
    bundle: ExportBundle, catalog: Catalog
) -> tuple[dict[tuple[CatalogKind, str], str], list[tuple[CatalogKind, str, CatalogItem]]]:
    """Сопоставить записи файла с записями системы.

    Возвращает отображение (вид, id в файле) -> id в системе для найденных записей
    и список записей, которые нужно создать (с их id из файла).
    """
    found: dict[tuple[CatalogKind, str], str] = {}
    missing: list[tuple[CatalogKind, str, CatalogItem]] = []
    for kind in KINDS:
        existing = {
            item.model_dump_json(): item_id for item_id, item in catalog.items(kind).items()
        }
        for file_id, data in bundle.catalog.get(kind, {}).items():
            item = parse_item(kind, data)
            match = existing.get(item.model_dump_json())
            if match is not None:
                found[(kind, file_id)] = match
            else:
                missing.append((kind, file_id, item))
    return found, missing


def check_references(bundle: ExportBundle) -> None:
    """Все ссылки машин должны вести на записи из файла."""
    for machine in bundle.machines:
        for kind, item_id in referenced(machine.config):
            if item_id not in bundle.catalog.get(kind, {}):
                raise CatalogMismatchError(
                    f"machine {machine.config.name!r} refers to {kind} {item_id!r} "
                    "that is not in the file"
                )


def remap(config: MachineConfig, ids: dict[tuple[CatalogKind, str], str]) -> MachineConfig:
    """Переписать ссылки машины на id записей в этой системе."""
    config = config.model_copy(deep=True)
    config.tank_type = ids[("tank", config.tank_type)]
    config.pump.model = ids[("pump", config.pump.model)]
    if isinstance(config.plumbing, CollectorPlumbingConfig):
        config.plumbing.collector_type = ids[("collector", config.plumbing.collector_type)]
    if config.power_group is not None:
        config.power_group = ids[("power", config.power_group)]
    for route in config.routes:
        if route.schedule_link is not None:
            route.schedule_link.template = ids[("schedule", route.schedule_link.template)]
    return config
