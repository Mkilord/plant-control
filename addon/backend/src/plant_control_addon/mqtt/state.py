"""Что публикуется в тему состояния машины."""

from typing import Any

from plant_control.domain.problems import Problem

from plant_control_addon.registry import MachineEntry


def state_payload(entry: MachineEntry, problems: list[Problem]) -> dict[str, Any]:
    machine = entry.machine
    tank = machine.tank
    capacity = tank.geometry.capacity_ml()
    blocking = [p for p in problems if p.blocking]

    if entry.is_busy:
        status = "watering"
    elif blocking:
        status = "problem"
    else:
        status = "idle"

    last = entry.last_watering
    return {
        "status": status,
        "water_ml": round(tank.volume_ml),
        "water_usable_ml": round(tank.usable_volume_ml),
        "water_percent": round(tank.volume_ml / capacity * 100) if capacity else 0,
        "level_mm": round(tank.level_mm),
        "pump": machine.pump.state.value,
        "busy": entry.is_busy,
        "last_watering": last.started_at.isoformat() if last else None,
        "last_watering_ok": last.ok if last else None,
        "problem": "yes" if problems else "no",
        "problems": [
            f"{p.kind.value}: {p.details}" if p.details else p.kind.value for p in problems
        ],
        "doses": {route.id: route.default_dose_ml for route in entry.config.routes},
    }
