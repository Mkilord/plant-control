"""Уведомления и события в Home Assistant.

Ядро выдаёт событие (что случилось), здесь оно превращается в текст и уходит
в HA: уведомление через сервис (persistent_notification или notify.*),
событие - на шину, чтобы автоматизации могли реагировать сами.
"""

import logging
from typing import Any, Protocol

from plant_control.application.notifications import Event, EventKind

log = logging.getLogger(__name__)

# Префикс событий на шине: plant_control_watering_done и так далее.
EVENT_PREFIX = "plant_control"

TITLES: dict[EventKind, str] = {
    EventKind.WATERING_DONE: "Полив выполнен",
    EventKind.WATERING_FAILED: "Полив не удался",
    EventKind.PROBLEM_OPENED: "Проблема с поливом",
    EventKind.PROBLEM_CLOSED: "Проблема решена",
    EventKind.SCHEDULE_SKIPPED: "Полив по расписанию пропущен",
}

PROBLEMS: dict[str, str] = {
    "ha_disconnected": "нет связи с Home Assistant",
    "pump_entity_missing": "насос не найден в Home Assistant",
    "valve_entity_missing": "клапан не найден в Home Assistant",
    "pump_state_unknown": "состояние насоса неизвестно",
    "valve_state_unknown": "состояние клапана неизвестно",
    "pump_overrun": "насос работал дольше предела",
    "tank_empty": "в баке нет воды",
    "tank_low": "в баке мало воды",
    "watering_failed": "полив не удался",
    "schedule_skipped": "полив по расписанию пропущен",
}

REASONS: dict[str, str] = {
    "too_late": "время полива давно прошло",
    "recently_watered": "полив уже был недавно",
}


def message_for(event: Event) -> str:
    """Человеческий текст события."""
    data = event.data
    machine = event.machine_name
    match event.kind:
        case EventKind.WATERING_DONE:
            return f"{machine}: полито {_plant(data)}, {_dose(data)}."
        case EventKind.WATERING_FAILED:
            return f"{machine}: не удалось полить {_plant(data)}. {data.get('error', '')}".strip()
        case EventKind.PROBLEM_OPENED:
            reason = PROBLEMS.get(str(data.get("problem")), str(data.get("problem")))
            details = str(data.get("details") or "")
            text = f"{machine}: {reason}"
            return f"{text} ({details})." if details else f"{text}."
        case EventKind.PROBLEM_CLOSED:
            reason = PROBLEMS.get(str(data.get("problem")), str(data.get("problem")))
            return f"{machine}: {reason} - больше не наблюдается."
        case EventKind.SCHEDULE_SKIPPED:
            reason = REASONS.get(str(data.get("reason")), str(data.get("reason")))
            return f"{machine}: полив {_plant(data)} пропущен, {reason}."


def _plant(data: dict[str, Any]) -> str:
    route = data.get("route_id")
    return f"«{route}»" if route else "растение"


def _dose(data: dict[str, Any]) -> str:
    dose = data.get("dose_ml")
    return f"{round(float(dose))} мл" if dose is not None else "доза не указана"


class ServiceDataCaller(Protocol):
    async def call_service_data(self, domain: str, service: str, data: dict[str, Any]) -> None: ...


class EventFirer(Protocol):
    async def fire_event(self, event_type: str, data: dict[str, Any]) -> None: ...


class HaNotifier:
    """Реализация NotifierPort: уведомление через сервис Home Assistant."""

    def __init__(self, ha: ServiceDataCaller, service: str) -> None:
        domain, _, name = service.partition(".")
        if not name:
            raise ValueError(f"notify service must look like domain.service, got {service!r}")
        self._ha = ha
        self._domain = domain
        self._service = name

    async def send(self, event: Event) -> None:
        data: dict[str, Any] = {
            "title": TITLES[event.kind],
            "message": message_for(event),
        }
        if self._domain == "persistent_notification":
            # Одна проблема - одно уведомление: повтор заменит прежнее, а не добавит второе.
            data["notification_id"] = f"{EVENT_PREFIX}_{event.machine_id}_{event.kind.value}"
        await self._ha.call_service_data(self._domain, self._service, data)


class HaEventSink:
    """Реализация EventSinkPort: событие на шине Home Assistant."""

    def __init__(self, ha: EventFirer) -> None:
        self._ha = ha

    async def publish(self, event: Event) -> None:
        await self._ha.fire_event(
            f"{EVENT_PREFIX}_{event.kind.value}",
            {
                "machine_id": event.machine_id,
                "machine_name": event.machine_name,
                "at": event.at.isoformat(),
                **event.data,
            },
        )
