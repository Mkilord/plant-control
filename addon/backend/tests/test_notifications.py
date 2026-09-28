"""Тесты уведомлений и событий Home Assistant."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from plant_control.application.notifications import Event, EventKind

from plant_control_addon.api.app import create_app
from plant_control_addon.ha.client import HomeAssistantUnavailableError
from plant_control_addon.notifications import HaEventSink, HaNotifier, message_for
from plant_control_addon.settings import Settings
from tests.conftest import FakeGateway, running, settings
from tests.test_machines_api import SIMPLE, create, wait_idle

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def event(kind: EventKind, **data: Any) -> Event:
    return Event(kind, "m-1", "Фикус", T0, data=data)


# --- Тексты ---


def test_texts_name_the_machine_and_the_plant() -> None:
    done = message_for(event(EventKind.WATERING_DONE, route_id="Монстера", dose_ml=120.4))
    assert done == "Фикус: полито «Монстера», 120 мл."

    failed = message_for(
        event(EventKind.WATERING_FAILED, route_id="Монстера", error="нет связи с реле")
    )
    assert failed == "Фикус: не удалось полить «Монстера». нет связи с реле"

    opened = message_for(event(EventKind.PROBLEM_OPENED, problem="tank_empty", details="0 мл"))
    assert opened == "Фикус: в баке нет воды (0 мл)."

    closed = message_for(event(EventKind.PROBLEM_CLOSED, problem="tank_empty"))
    assert closed == "Фикус: в баке нет воды - больше не наблюдается."

    skipped = message_for(
        event(EventKind.SCHEDULE_SKIPPED, route_id="Монстера", reason="recently_watered")
    )
    assert skipped == "Фикус: полив «Монстера» пропущен, полив уже был недавно."


# --- Адаптеры ---


async def test_notifier_sends_title_and_message(gateway: FakeGateway) -> None:
    notifier = HaNotifier(gateway, "persistent_notification.create")

    await notifier.send(event(EventKind.WATERING_FAILED, route_id="main", error="boom"))

    sent = gateway.notifications[0]
    assert sent["service"] == "persistent_notification.create"
    assert sent["title"] == "Полив не удался"
    # Повтор той же беды заменяет прежнее уведомление, а не копит их.
    assert sent["notification_id"] == "plant_control_m-1_watering_failed"


async def test_notifier_works_with_notify_services(gateway: FakeGateway) -> None:
    notifier = HaNotifier(gateway, "notify.mobile_app_phone")

    await notifier.send(event(EventKind.WATERING_DONE, route_id="main", dose_ml=100))

    sent = gateway.notifications[0]
    assert sent["service"] == "notify.mobile_app_phone"
    assert "notification_id" not in sent


async def test_event_sink_fires_prefixed_event(gateway: FakeGateway) -> None:
    await HaEventSink(gateway).publish(event(EventKind.WATERING_DONE, route_id="main", dose_ml=100))

    name, data = gateway.events[0]
    assert name == "plant_control_watering_done"
    assert data["machine_id"] == "m-1"
    assert data["machine_name"] == "Фикус"
    assert data["route_id"] == "main"
    assert data["at"] == T0.isoformat()


# --- Настройки ---


def test_rules_come_from_settings() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        notify_events="watering_done,problem_opened",
        notify_quiet_from="23:00",
        notify_quiet_to="07:30",
        timezone="Europe/Moscow",
    )
    rules = settings.notification_rules

    assert rules.kinds == frozenset({EventKind.WATERING_DONE, EventKind.PROBLEM_OPENED})
    assert rules.quiet_to is not None
    assert (rules.quiet_to.hour, rules.quiet_to.minute) == (7, 30)
    assert rules.timezone == "Europe/Moscow"


# --- Через приложение ---


async def test_watering_publishes_event_to_the_bus(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await api.post(f"/api/machines/{machine_id}/tank/refill", json={})
    await api.post(f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 50})
    await wait_idle(api, machine_id)

    fired = [name for name, _ in gateway.events]
    assert "plant_control_watering_done" in fired
    # Удачный полив по умолчанию не беспокоит человека: он виден в интерфейсе.
    assert gateway.notifications == []


class BrokenPumpGateway(FakeGateway):
    """Реле насоса не отвечает: полив обязан провалиться."""

    async def call_service(self, domain: str, service: str, entity_id: str) -> None:
        if service == "turn_on":
            raise HomeAssistantUnavailableError("реле не отвечает")
        await super().call_service(domain, service, entity_id)


async def test_failed_watering_notifies(tmp_path: Path) -> None:
    gateway = BrokenPumpGateway()
    app = create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    async with running(app) as api:
        machine_id = (await create(api, SIMPLE))["id"]
        await api.post(f"/api/machines/{machine_id}/tank/refill", json={})
        await api.post(
            f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 50}
        )
        await wait_idle(api, machine_id)

        assert any(name == "plant_control_watering_failed" for name, _ in gateway.events)
        titles = [sent["title"] for sent in gateway.notifications]
        assert "Полив не удался" in titles
