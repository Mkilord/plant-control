"""Перевод машин старого формата на справочники.

Раньше машина хранила бак, насос, задержки клапанов и группу питания у себя.
Теперь это записи справочников, а машина ссылается на них. Миграция создаёт записи
из текущих настроек, одинаковые схлопывает в одну и переписывает машины на ссылки.
Поведение полива не меняется: собранная машина получается той же.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from plant_control_addon.catalog import (
    CatalogItem,
    CatalogKind,
    CollectorType,
    PowerGroupConfig,
    PumpModel,
    TankType,
    new_id,
)


def is_legacy(config: dict[str, Any]) -> bool:
    """Старый формат: бак и насос лежат в машине целиком."""
    tank = config.get("tank")
    return isinstance(tank, dict) and "geometry" in tank


@dataclass
class Migration:
    # Новые записи справочников: (вид, id, запись).
    items: list[tuple[CatalogKind, str, CatalogItem]] = field(default_factory=list)
    # Переписанные машины: id -> конфигурация в новом формате (dict для MachineConfig).
    machines: dict[str, dict[str, Any]] = field(default_factory=dict)
    _seen: dict[tuple[CatalogKind, str], str] = field(default_factory=dict)

    def add(self, kind: CatalogKind, key: dict[str, Any], item: CatalogItem) -> str:
        """Добавить запись или вернуть id уже добавленной с теми же настройками."""
        fingerprint = json.dumps(key, sort_keys=True, default=str)
        existing = self._seen.get((kind, fingerprint))
        if existing is not None:
            return existing
        item_id = new_id(kind)
        self._seen[(kind, fingerprint)] = item_id
        self.items.append((kind, item_id, item))
        return item_id


def migrate(rows: list[tuple[str, dict[str, Any]]]) -> Migration:
    """rows - (id машины, конфигурация). Машины нового формата не трогает."""
    result = Migration()
    legacy = [(machine_id, config) for machine_id, config in rows if is_legacy(config)]

    # Группы питания: предел и пауза как считались раньше, по всем участникам.
    groups: dict[str, list[dict[str, Any]]] = {}
    for _, config in legacy:
        name = str(config.get("power_group") or "")
        if name:
            groups.setdefault(name, []).append(config)
    group_ids: dict[str, str] = {}
    for name, members in groups.items():
        group = PowerGroupConfig(
            name=name,
            max_concurrent=min(int(c.get("power_limit", 1)) for c in members),
            min_start_gap_s=max(float(c.get("power_gap_s", 2)) for c in members),
        )
        group_ids[name] = result.add("power", {"name": name}, group)

    for machine_id, config in legacy:
        name = str(config.get("name") or machine_id)
        tank = config["tank"]
        tank_id = result.add(
            "tank",
            {"geometry": tank["geometry"], "reserve_ml": tank.get("reserve_ml", 0)},
            TankType(
                name=f"Бак ({name})",
                geometry=tank["geometry"],
                reserve_ml=tank.get("reserve_ml", 0),
            ),
        )
        pump = config["pump"]
        pump_key = {
            "flow": pump.get("flow"),
            "max_runtime_s": pump.get("max_runtime_s"),
            "cooldown_s": pump.get("cooldown_s", 0),
        }
        pump_id = result.add(
            "pump",
            pump_key,
            PumpModel(
                name=f"Насос ({name})",
                flow=pump.get("flow"),
                max_runtime_s=pump.get("max_runtime_s"),
                cooldown_s=pump.get("cooldown_s", 0),
            ),
        )
        plumbing = dict(config["plumbing"])
        if plumbing.get("type") == "collector":
            timings = config.get("timings") or {}
            lead = timings.get("valve_lead_s", 0.5)
            lag = timings.get("valve_lag_s", 0.5)
            outlets = max(2, len(config.get("routes", [])))
            plumbing["collector_type"] = result.add(
                "collector",
                {"outlets": outlets, "lead": lead, "lag": lag},
                CollectorType(
                    name=f"Коллектор на {outlets} {_outlets_word(outlets)}",
                    outlets=outlets,
                    valve_lead_s=lead,
                    valve_lag_s=lag,
                ),
            )
        group_name = str(config.get("power_group") or "")
        result.machines[machine_id] = {
            "name": name,
            "tank_type": tank_id,
            "pump": {"model": pump_id, "entity_id": pump["entity_id"]},
            "plumbing": plumbing,
            "head_model": config.get("head_model", "mid"),
            # Старые машины без поля жили на паспорте насоса.
            "flow_mode": config.get("flow_mode", "advanced"),
            "base_route": config.get("base_route"),
            "routes": config["routes"],
            "power_group": group_ids.get(group_name),
        }
    return result


def _outlets_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "выход"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "выхода"
    return "выходов"
