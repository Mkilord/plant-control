"""Темы и описания сущностей для MQTT discovery.

Home Assistant сам создаёт сущности, когда видит в теме discovery описание
устройства. Здесь только чистые функции: собрать темы и полезную нагрузку.
Их легко проверить тестами, не поднимая брокер.
"""

from typing import Any

from plant_control_addon.config import MachineConfig
from plant_control_addon.registry import MachineEntry

# Корень наших тем. Состояния публикуются сюда, команды приходят сюда же.
ROOT = "plant_control"
AVAILABILITY = f"{ROOT}/status"
MANUFACTURER = "PlantControl"


def machine_topic(machine_id: str, suffix: str) -> str:
    return f"{ROOT}/{machine_id}/{suffix}"


def state_topic(machine_id: str) -> str:
    return machine_topic(machine_id, "state")


def command_topic(machine_id: str, name: str) -> str:
    return machine_topic(machine_id, f"cmd/{name}")


def device_block(entry: MachineEntry) -> dict[str, Any]:
    return {
        "identifiers": [f"{ROOT}_{entry.id}"],
        "name": entry.config.name,
        "manufacturer": MANUFACTURER,
        "model": "Watering machine",
    }


def _entity(
    entry: MachineEntry,
    component: str,
    object_id: str,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Тема discovery и её содержимое."""
    topic = f"{{prefix}}/{component}/{ROOT}_{entry.id}/{object_id}/config"
    body: dict[str, Any] = {
        "unique_id": f"{ROOT}_{entry.id}_{object_id}",
        "object_id": f"{ROOT}_{entry.id}_{object_id}",
        "device": device_block(entry),
        "availability_topic": AVAILABILITY,
        "payload_available": "online",
        "payload_not_available": "offline",
        **payload,
    }
    return topic, body


def discovery(entry: MachineEntry, prefix: str) -> list[tuple[str, dict[str, Any]]]:
    """Все сущности одной машины: датчики, кнопки, поля дозы."""
    config: MachineConfig = entry.config
    state = state_topic(entry.id)
    items: list[tuple[str, dict[str, Any]]] = [
        _entity(
            entry,
            "sensor",
            "water",
            {
                "name": "Вода",
                "state_topic": state,
                "value_template": "{{ value_json.water_ml }}",
                "unit_of_measurement": "mL",
                "device_class": "volume_storage",
                "state_class": "measurement",
                "icon": "mdi:cup-water",
            },
        ),
        _entity(
            entry,
            "sensor",
            "water_percent",
            {
                "name": "Заполнение бака",
                "state_topic": state,
                "value_template": "{{ value_json.water_percent }}",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:water-percent",
            },
        ),
        _entity(
            entry,
            "sensor",
            "status",
            {
                "name": "Состояние",
                "state_topic": state,
                "value_template": "{{ value_json.status }}",
                "icon": "mdi:watering-can",
            },
        ),
        _entity(
            entry,
            "sensor",
            "last_watering",
            {
                "name": "Последний полив",
                "state_topic": state,
                "value_template": "{{ value_json.last_watering }}",
                "device_class": "timestamp",
            },
        ),
        _entity(
            entry,
            "binary_sensor",
            "problem",
            {
                "name": "Проблема",
                "state_topic": state,
                "value_template": "{{ value_json.problem }}",
                "payload_on": "yes",
                "payload_off": "no",
                "device_class": "problem",
                "json_attributes_topic": state,
                "json_attributes_template": "{{ {'problems': value_json.problems} | tojson }}",
            },
        ),
        _entity(
            entry,
            "button",
            "tank_filled",
            {
                "name": "Бак залит",
                "command_topic": command_topic(entry.id, "tank_filled"),
                "icon": "mdi:water-plus",
            },
        ),
    ]

    for route in config.routes:
        plant = route.name or route.id
        items.append(
            _entity(
                entry,
                "button",
                f"water_{route.id}",
                {
                    "name": f"Полить: {plant}",
                    "command_topic": command_topic(entry.id, f"water/{route.id}"),
                    "icon": "mdi:water",
                },
            )
        )
        items.append(
            _entity(
                entry,
                "number",
                f"dose_{route.id}",
                {
                    "name": f"Доза: {plant}",
                    "state_topic": state,
                    "value_template": f"{{{{ value_json.doses['{route.id}'] }}}}",
                    "command_topic": command_topic(entry.id, f"dose/{route.id}"),
                    "min": 10,
                    "max": 5000,
                    "step": 10,
                    "unit_of_measurement": "mL",
                    "mode": "box",
                    "icon": "mdi:beaker",
                },
            )
        )

    return [(topic.format(prefix=prefix), body) for topic, body in items]
