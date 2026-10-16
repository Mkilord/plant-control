"""Справочники: типы баков, модели насосов, типы коллекторов, расписания, группы питания.

Запись справочника создаётся один раз и используется многими машинами. Машина
хранит ссылку (id), а не копию: изменение записи действует на все машины сразу.
"""

import uuid
from datetime import timedelta
from typing import Literal

from plant_control.domain.power import PowerGroup
from pydantic import BaseModel, Field

from plant_control_addon.config import (
    FlowConfig,
    GeometryConfig,
    RuleConfig,
)

# Предел работы насоса по умолчанию. Его можно выключить, задав None.
DEFAULT_MAX_RUNTIME_S = 300.0

CatalogKind = Literal["tank", "pump", "collector", "schedule", "power"]
KINDS: tuple[CatalogKind, ...] = ("tank", "pump", "collector", "schedule", "power")

NAME = Field(min_length=1, max_length=100)


class UnknownCatalogItemError(Exception):
    pass


class CatalogItemInUseError(Exception):
    def __init__(self, message: str, machines: list[str]) -> None:
        super().__init__(message)
        self.machines = machines


class TankType(BaseModel):
    """Тип бака: форма и недоступный насосу запас. Объём воды хранит машина."""

    name: str = NAME
    geometry: GeometryConfig
    reserve_ml: float = Field(default=0, ge=0)


class PumpModel(BaseModel):
    """Модель насоса: ограничения и паспорт. Сущность HA привязывает машина."""

    name: str = NAME
    # Предел непрерывной работы. None - предел выключен.
    max_runtime_s: float | None = Field(default=DEFAULT_MAX_RUNTIME_S, gt=0)
    cooldown_s: float = Field(default=0, ge=0)
    # Паспортная модель расхода. Нужна только в расширенном режиме.
    flow: FlowConfig | None = None


class CollectorType(BaseModel):
    """Тип коллектора: сколько выходов и как клапан ждёт насос."""

    name: str = NAME
    outlets: int = Field(ge=2, le=32)
    # Клапан открывается раньше насоса и закрывается позже.
    valve_lead_s: float = Field(default=0.5, ge=0)
    valve_lag_s: float = Field(default=0.5, ge=0)


class ScheduleTemplate(BaseModel):
    """Расписание, общее для многих растений. dose_ml задана - она важнее дозы растения."""

    name: str = NAME
    rule: RuleConfig
    dose_ml: float | None = Field(default=None, gt=0)
    season_factor: float = Field(default=1.0, gt=0)
    catch_up_h: float = Field(default=3, ge=0)
    min_gap_h: float = Field(default=6, ge=0)


class PowerGroupConfig(BaseModel):
    """Группа питания: машины на одном блоке и правила их совместной работы."""

    name: str = NAME
    max_concurrent: int = Field(default=1, ge=1)
    min_start_gap_s: float = Field(default=2, ge=0)
    # Сколько заявка может ждать места в группе. None - сколько угодно.
    max_wait_min: float | None = Field(default=None, gt=0)

    def group(self, group_id: str) -> PowerGroup:
        return PowerGroup(
            id=group_id,
            name=self.name,
            max_concurrent=self.max_concurrent,
            min_start_gap=timedelta(seconds=self.min_start_gap_s),
            max_wait=timedelta(minutes=self.max_wait_min) if self.max_wait_min else None,
        )


CatalogItem = TankType | PumpModel | CollectorType | ScheduleTemplate | PowerGroupConfig

MODELS: dict[CatalogKind, type[BaseModel]] = {
    "tank": TankType,
    "pump": PumpModel,
    "collector": CollectorType,
    "schedule": ScheduleTemplate,
    "power": PowerGroupConfig,
}

PREFIX: dict[CatalogKind, str] = {
    "tank": "tank",
    "pump": "pump",
    "collector": "coll",
    "schedule": "sched",
    "power": "power",
}


def new_id(kind: CatalogKind) -> str:
    return f"{PREFIX[kind]}-{uuid.uuid4().hex[:8]}"


def parse_item(kind: CatalogKind, data: str | dict[str, object]) -> CatalogItem:
    model = MODELS[kind]
    item = model.model_validate_json(data) if isinstance(data, str) else model.model_validate(data)
    assert isinstance(item, CatalogItem)
    return item


class Catalog:
    """Все записи справочников в памяти. Источник правды - база, см. MachineRegistry."""

    def __init__(self) -> None:
        self._items: dict[CatalogKind, dict[str, CatalogItem]] = {kind: {} for kind in KINDS}

    def put(self, kind: CatalogKind, item_id: str, item: CatalogItem) -> None:
        if not isinstance(item, MODELS[kind]):
            raise TypeError(f"{type(item).__name__} is not a {kind} item")
        self._items[kind][item_id] = item

    def remove(self, kind: CatalogKind, item_id: str) -> None:
        self.get(kind, item_id)
        del self._items[kind][item_id]

    def items(self, kind: CatalogKind) -> dict[str, CatalogItem]:
        return dict(self._items[kind])

    def get(self, kind: CatalogKind, item_id: str) -> CatalogItem:
        try:
            return self._items[kind][item_id]
        except KeyError:
            raise UnknownCatalogItemError(f"unknown {kind} {item_id!r}") from None

    def tank(self, item_id: str) -> TankType:
        item = self.get("tank", item_id)
        assert isinstance(item, TankType)
        return item

    def pump(self, item_id: str) -> PumpModel:
        item = self.get("pump", item_id)
        assert isinstance(item, PumpModel)
        return item

    def collector(self, item_id: str) -> CollectorType:
        item = self.get("collector", item_id)
        assert isinstance(item, CollectorType)
        return item

    def schedule(self, item_id: str) -> ScheduleTemplate:
        item = self.get("schedule", item_id)
        assert isinstance(item, ScheduleTemplate)
        return item

    def power(self, item_id: str) -> PowerGroupConfig:
        item = self.get("power", item_id)
        assert isinstance(item, PowerGroupConfig)
        return item
