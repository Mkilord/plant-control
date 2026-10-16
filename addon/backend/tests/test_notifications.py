"""Тесты уведомлений и событий Home Assistant."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from plant_control.application.notifications import Event, EventKind

from plant_control_addon.api.app import create_app
from plant_control_addon.ha.client import HomeAssistantUnavailableError
from plant_control_addon.notification_settings import EventText, NotificationSettings
from plant_control_addon.notifications import (
    HaEventSink,
    NoPushTargetsError,
    PushNotifier,
    human_error,
    message_for,
    title_for,
)
from tests.conftest import FakeGateway, running, settings
from tests.test_machines_api import SIMPLE, create, wait_idle

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def event(kind: EventKind, **data: Any) -> Event:
    return Event(kind, "m-1", "Фикус", T0, data=data)


# --- Тексты ---


def test_texts_name_the_machine_and_the_plant() -> None:
    done = message_for(event(EventKind.WATERING_DONE, route_id="Монстера", dose_ml=120.4))
    assert done == "🪴 Фикус: полили «Монстера», 120 мл."

    failed = message_for(
        event(EventKind.WATERING_FAILED, route_id="Монстера", error="нет связи с реле")
    )
    assert failed == "🥀 Фикус: не удалось полить «Монстера» - нет связи с реле."

    opened = message_for(event(EventKind.PROBLEM_OPENED, problem="tank_empty", details="0 мл"))
    assert opened == "Фикус: в баке нет воды. 0 мл"

    closed = message_for(event(EventKind.PROBLEM_CLOSED, problem="tank_empty"))
    assert closed == "👌 Фикус: в баке нет воды - больше не мешает."

    skipped = message_for(
        event(EventKind.SCHEDULE_SKIPPED, route_id="Монстера", reason="recently_watered")
    )
    assert skipped == "🗓️ Фикус: «Монстера» не поливаем - полив уже был недавно."


# --- Адаптеры ---


async def test_push_goes_to_every_phone_with_the_app(gateway: FakeGateway) -> None:
    gateway.services["notify"]["mobile_app_tablet"] = {}
    notifier = PushNotifier(gateway, open_url="/hassio/ingress/plant_control")

    await notifier.send(event(EventKind.WATERING_FAILED, route_id="main", error="boom"))

    # Только телефоны: notify.notify и persistent_notification - не пуш.
    services = [sent["service"] for sent in gateway.notifications]
    assert services == ["notify.mobile_app_phone", "notify.mobile_app_tablet"]
    sent = gateway.notifications[0]
    assert sent["title"] == "❌ Полив не удался"
    assert sent["message"] == "🥀 Фикус: не удалось полить «main» - boom."
    data = sent["data"]
    # Повтор той же беды заменяет прежний пуш, а не копит их.
    assert data["tag"] == "plant_control_m-1_watering_failed"
    assert data["group"] == "plant_control"
    assert data["url"] == data["clickAction"] == "/hassio/ingress/plant_control"
    assert "priority" not in data


async def test_push_goes_only_to_chosen_phones(gateway: FakeGateway) -> None:
    notifier = PushNotifier(gateway, ["notify.mobile_app_pixel", " mobile_app_iphone "])

    await notifier.send(event(EventKind.WATERING_DONE, route_id="main", dose_ml=100))

    services = [sent["service"] for sent in gateway.notifications]
    assert services == ["notify.mobile_app_pixel", "notify.mobile_app_iphone"]


async def test_no_phones_is_an_error(gateway: FakeGateway) -> None:
    gateway.services["notify"] = {"persistent_notification": {}}

    with pytest.raises(NoPushTargetsError):
        await PushNotifier(gateway).send(event(EventKind.WATERING_DONE, dose_ml=1))


class FlakyPhoneGateway(FakeGateway):
    async def call_service_data(self, domain: str, service: str, data: dict[str, Any]) -> None:
        if service == "mobile_app_old":
            raise HomeAssistantUnavailableError("телефон удалён")
        await super().call_service_data(domain, service, data)


async def test_one_broken_phone_does_not_stop_the_rest() -> None:
    gateway = FlakyPhoneGateway()
    notifier = PushNotifier(gateway, ["mobile_app_old", "mobile_app_phone"])

    await notifier.send(event(EventKind.WATERING_DONE, dose_ml=1))

    assert [sent["service"] for sent in gateway.notifications] == ["notify.mobile_app_phone"]


async def test_push_fails_when_no_phone_got_it() -> None:
    notifier = PushNotifier(FlakyPhoneGateway(), ["mobile_app_old"])

    with pytest.raises(RuntimeError, match="every phone"):
        await notifier.send(event(EventKind.WATERING_DONE, dose_ml=1))


def urgent_problem() -> Event:
    return Event(
        EventKind.PROBLEM_OPENED,
        "m-1",
        "Фикус",
        T0,
        data={"problem": "tank_empty", "target": "tank"},
        urgent=True,
    )


async def test_urgent_push_is_delivered_at_once(gateway: FakeGateway) -> None:
    await PushNotifier(gateway).send(urgent_problem())

    data = gateway.notifications[0]["data"]
    assert data["priority"] == "high"
    assert data["ttl"] == 0
    assert data["channel"] == "PlantControl: срочно"
    assert data["push"] == {"interruption-level": "time-sensitive"}


async def test_critical_push_sounds_in_silent_mode(gateway: FakeGateway) -> None:
    await PushNotifier(gateway, critical=True).send(urgent_problem())

    data = gateway.notifications[0]["data"]
    assert data["channel"] == "alarm_stream"
    assert data["push"]["interruption-level"] == "critical"
    assert data["push"]["sound"]["critical"] == 1


async def test_closed_problem_replaces_its_push(gateway: FakeGateway) -> None:
    notifier = PushNotifier(gateway)
    await notifier.send(urgent_problem())
    await notifier.send(event(EventKind.PROBLEM_CLOSED, problem="tank_empty", target="tank"))

    opened, closed = (sent["data"]["tag"] for sent in gateway.notifications)
    assert opened == closed == "plant_control_m-1_problem_tank_empty_tank"
    assert "priority" not in gateway.notifications[1]["data"]


async def test_event_sink_fires_prefixed_event(gateway: FakeGateway) -> None:
    await HaEventSink(gateway).publish(event(EventKind.WATERING_DONE, route_id="main", dose_ml=100))

    name, data = gateway.events[0]
    assert name == "plant_control_watering_done"
    assert data["machine_id"] == "m-1"
    assert data["machine_name"] == "Фикус"
    assert data["route_id"] == "main"
    assert data["at"] == T0.isoformat()


# --- Настройки ---


def test_rules_come_from_settings_model() -> None:
    model = NotificationSettings(
        events=[EventKind.WATERING_DONE, EventKind.PROBLEM_OPENED],
        quiet_from="23:00",
        quiet_to="7:30",
        devices=["mobile_app_pixel", "notify.mobile_app_iphone", "mobile_app_pixel"],
    )
    rules = model.rules("Europe/Moscow")

    assert model.devices == ["mobile_app_pixel", "mobile_app_iphone"]
    assert rules.kinds == frozenset({EventKind.WATERING_DONE, EventKind.PROBLEM_OPENED})
    assert rules.quiet_to is not None
    assert (rules.quiet_to.hour, rules.quiet_to.minute) == (7, 30)
    assert rules.timezone == "Europe/Moscow"


def test_bad_settings_are_rejected() -> None:
    with pytest.raises(ValueError):
        NotificationSettings(quiet_from="25:00")
    with pytest.raises(ValueError):
        NotificationSettings(devices=["notify.bad name"])
    with pytest.raises(ValueError, match="unknown placeholders"):
        EventText(message="{machine}: {nope}")


def test_custom_texts_work_only_in_advanced_mode() -> None:
    texts = {EventKind.WATERING_DONE: EventText(title="Готово", message="{plant} полито в {time}")}
    done = event(EventKind.WATERING_DONE, route_id="Монстера", dose_ml=100)

    plain = NotificationSettings(texts=texts).custom_texts()
    advanced = NotificationSettings(texts=texts, advanced=True).custom_texts()

    assert title_for(done, plain) == "💧 Полито"
    assert title_for(done, advanced) == "Готово"
    assert message_for(done, advanced, "Europe/Moscow") == "«Монстера» полито в 15:00"


def test_empty_details_leave_no_brackets() -> None:
    opened = message_for(event(EventKind.PROBLEM_OPENED, problem="tank_empty"))
    assert opened == "Фикус: в баке нет воды."
    assert title_for(event(EventKind.PROBLEM_OPENED, problem="tank_empty")) == (
        "🚱 Проблема с поливом"
    )


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
        assert "❌ Полив не удался" in titles


async def test_test_push_endpoint(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    devices = await api.get("/api/notifications/devices")
    assert devices.json() == {"available": ["mobile_app_phone"], "targets": ["mobile_app_phone"]}

    response = await api.post("/api/notifications/test")

    assert response.status_code == 200
    assert response.json()["devices"] == ["mobile_app_phone"]
    assert gateway.notifications[0]["data"]["tag"] == "plant_control_test"


async def test_test_push_without_phones(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    gateway.services["notify"] = {}

    response = await api.post("/api/notifications/test")

    assert response.status_code == 404


async def test_settings_are_saved_applied_and_survive_restart(tmp_path: Path) -> None:
    gateway = FakeGateway()
    gateway.services["notify"]["mobile_app_tablet"] = {}
    body = {
        "devices": ["mobile_app_tablet"],
        "events": ["watering_done"],
        "advanced": True,
        "texts": {"watering_done": {"title": "Готово", "message": "{machine}: {dose}"}},
    }
    app = create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    async with running(app) as api:
        saved = await api.put("/api/notifications/settings", json=body)
        assert saved.status_code == 200, saved.text
        devices = (await api.get("/api/notifications/devices")).json()
        assert devices["targets"] == ["mobile_app_tablet"]

        machine_id = (await create(api, SIMPLE))["id"]
        await api.post(f"/api/machines/{machine_id}/tank/refill", json={})
        await api.post(
            f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 50}
        )
        await wait_idle(api, machine_id)

        sent = [n for n in gateway.notifications if n["title"] == "Готово"]
        assert [n["service"] for n in sent] == ["notify.mobile_app_tablet"]
        assert sent[0]["message"] == "Фикус: 50 мл"

    app = create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    async with running(app) as api:
        again = (await api.get("/api/notifications/settings")).json()
        assert again["devices"] == ["mobile_app_tablet"]
        assert again["texts"]["watering_done"]["title"] == "Готово"


async def test_disabled_notifications_send_nothing(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    await api.put("/api/notifications/settings", json={"enabled": False})
    machine_id = (await create(api, SIMPLE))["id"]
    await api.put(f"/api/machines/{machine_id}/tank/volume", json={"volume_ml": 0})

    # Уведомления о проблемах уходят в фоне: дать им дойти.
    for _ in range(100):
        if gateway.events:
            break
        await asyncio.sleep(0.01)
    assert gateway.notifications == []
    # События на шину уходят всё равно.
    assert any(name == "plant_control_problem_opened" for name, _ in gateway.events)


async def test_templates_and_preview(api: httpx.AsyncClient) -> None:
    templates = (await api.get("/api/notifications/templates")).json()
    done = next(t for t in templates if t["kind"] == "watering_done")
    assert "plant" in done["placeholders"]

    preview = await api.post(
        "/api/notifications/preview",
        json={"kind": "watering_done", "text": {"title": "", "message": "Полито: {plant}"}},
    )
    assert preview.json() == {"title": "💧 Полито", "message": "Полито: «Монстера»"}


def test_errors_are_told_in_plain_words() -> None:
    assert human_error(
        "WateringBlockedError: watering is blocked: pump_entity_missing, tank_empty"
    ) == ("полив невозможен: насос не найден в Home Assistant, в баке нет воды")
    assert human_error("PumpControlError: relay timeout") == "не удалось переключить насос"
    assert human_error("ValueError: strange") == "strange"
    assert human_error("просто текст") == "просто текст"
