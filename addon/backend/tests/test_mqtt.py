"""Тесты моста MQTT: описания сущностей, состояние и команды из Home Assistant."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from plant_control.domain.problems import Observation, ProblemBoard, ProblemKind

from plant_control_addon.config import MachineConfig
from plant_control_addon.controller import Controller, SystemClock
from plant_control_addon.mqtt.bridge import MqttBridge
from plant_control_addon.mqtt.topics import AVAILABILITY, discovery, state_topic
from plant_control_addon.registry import MachineEntry, MachineRegistry
from plant_control_addon.settings import Settings
from plant_control_addon.storage import MachineStore
from tests.conftest import FakeGateway
from tests.test_machines_api import SIMPLE


class FakeSession:
    """Сессия брокера в памяти: помнит публикации и отдаёт подготовленные команды."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str, bool]] = []
        self.subscriptions: list[str] = []
        self.inbox: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    async def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        self.published.append((topic, payload, retain))

    async def subscribe(self, topic: str) -> None:
        self.subscriptions.append(topic)

    async def messages(self) -> AsyncIterator[tuple[str, str]]:
        while True:
            yield await self.inbox.get()

    def topics(self) -> list[str]:
        return [topic for topic, _, _ in self.published]

    def last(self, topic: str) -> dict[str, object]:
        for published, payload, _ in reversed(self.published):
            if published == topic:
                result: dict[str, object] = json.loads(payload)
                return result
        raise AssertionError(f"nothing published to {topic}")


@pytest.fixture
async def registry(tmp_path: Path) -> AsyncIterator[MachineRegistry]:
    registry = MachineRegistry(MachineStore(tmp_path / "test.db"))
    await registry.load()
    await registry.create(MachineConfig.model_validate(SIMPLE))
    yield registry


@pytest.fixture
def board() -> ProblemBoard:
    return ProblemBoard()


@pytest.fixture
def bridge(registry: MachineRegistry, board: ProblemBoard, gateway: FakeGateway) -> MqttBridge:
    controller = Controller(registry, gateway, clock=SystemClock())
    return MqttBridge(lambda: None, registry, controller, board)


def entry_of(registry: MachineRegistry) -> MachineEntry:
    return registry.entries()[0]


# --- Описания сущностей ---


def test_discovery_covers_sensors_buttons_and_doses(registry: MachineRegistry) -> None:
    entry = entry_of(registry)
    items = dict(discovery(entry, "homeassistant"))

    prefixes = {topic.split("/")[1] for topic in items}
    assert prefixes == {"sensor", "binary_sensor", "button", "number"}
    assert any(topic.endswith("/water/config") for topic in items)
    assert any(topic.endswith("/water_main/config") for topic in items)
    assert any(topic.endswith("/dose_main/config") for topic in items)
    assert any(topic.endswith("/tank_filled/config") for topic in items)

    for body in items.values():
        assert body["availability_topic"] == AVAILABILITY
        device = body["device"]
        assert isinstance(device, dict)
        assert device["identifiers"] == [f"plant_control_{entry.id}"]
        assert str(body["unique_id"]).startswith(f"plant_control_{entry.id}_")


# --- Публикация состояния ---


async def test_publish_all_sends_discovery_once_and_state_every_time(
    bridge: MqttBridge, registry: MachineRegistry
) -> None:
    session = FakeSession()
    entry = entry_of(registry)
    state = state_topic(entry.id)

    await bridge.publish_all(session)
    first = len(session.topics())
    assert state in session.topics()

    await bridge.publish_all(session)
    # Второй раз - только состояние.
    assert len(session.topics()) == first + 1
    assert all(retain for _, _, retain in session.published)


async def test_state_payload_shows_water_and_problems(
    bridge: MqttBridge, registry: MachineRegistry, board: ProblemBoard
) -> None:
    session = FakeSession()
    entry = entry_of(registry)
    entry.machine.tank.fill_full()
    board.observe(
        [Observation(entry.id, ProblemKind.TANK_EMPTY, details="нет воды")],
        SystemClock().now(),
    )

    await bridge.publish_all(session)
    payload = session.last(state_topic(entry.id))

    assert payload["status"] == "problem"
    assert payload["water_ml"] == round(entry.machine.tank.volume_ml)
    assert payload["water_percent"] == 100
    assert payload["problem"] == "yes"
    assert payload["problems"] == ["tank_empty: нет воды"]
    assert payload["doses"] == {"main": 100.0}


# --- Команды ---


async def test_tank_filled_button_fills_the_tank(
    bridge: MqttBridge, registry: MachineRegistry
) -> None:
    entry = entry_of(registry)
    entry.machine.tank.draw(500)
    before = entry.machine.tank.volume_ml

    await bridge.handle_command(f"plant_control/{entry.id}/cmd/tank_filled", "PRESS")

    assert entry.machine.tank.volume_ml > before


async def test_water_button_starts_watering(
    bridge: MqttBridge, registry: MachineRegistry, gateway: FakeGateway
) -> None:
    entry = entry_of(registry)
    entry.machine.tank.fill_full()
    before = entry.machine.tank.volume_ml

    await bridge.handle_command(f"plant_control/{entry.id}/cmd/water/main", "PRESS")
    assert entry.task is not None
    await entry.task

    assert entry.machine.tank.volume_ml < before
    assert gateway.commands() == ["turn_on switch.pump_1", "turn_off switch.pump_1"]
    assert entry.last_watering is not None
    assert entry.last_watering.ok


async def test_dose_field_updates_default_dose(
    bridge: MqttBridge, registry: MachineRegistry
) -> None:
    entry = entry_of(registry)

    await bridge.handle_command(f"plant_control/{entry.id}/cmd/dose/main", "250")

    assert registry.entry(entry.id).config.routes[0].default_dose_ml == 250


async def test_unknown_topic_is_ignored(bridge: MqttBridge) -> None:
    await bridge.handle_command("other/thing", "1")
    await bridge.handle_command("plant_control/m-1/cmd/fly", "1")


# --- Соединение ---


async def test_connect_announces_online_and_subscribes(bridge: MqttBridge) -> None:
    session = FakeSession()

    await bridge._on_connect(session)

    assert (AVAILABILITY, "online", True) in session.published
    assert session.subscriptions == ["plant_control/+/cmd/#"]


async def test_resolve_broker_falls_back_to_settings() -> None:
    from plant_control_addon.mqtt.transport import resolve_broker

    empty = Settings(_env_file=None)  # type: ignore[call-arg]
    assert await resolve_broker(empty) is None

    configured = Settings(_env_file=None, mqtt_host="core-mosquitto", mqtt_user="pc")  # type: ignore[call-arg]
    broker = await resolve_broker(configured)
    assert broker is not None
    assert (broker.host, broker.port, broker.username) == ("core-mosquitto", 1883, "pc")
