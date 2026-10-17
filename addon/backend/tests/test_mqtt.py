"""Тесты моста MQTT: описания сущностей, состояние и команды из Home Assistant."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from plant_control.domain.problems import Observation, ProblemBoard, ProblemKind

from plant_control_addon.catalog import PumpModel, TankType
from plant_control_addon.config import MachineConfig
from plant_control_addon.controller import Controller, SystemClock
from plant_control_addon.mqtt.bridge import MqttBridge
from plant_control_addon.mqtt.known import KnownMachines
from plant_control_addon.mqtt.settings import MqttManager, MqttSettingsIn
from plant_control_addon.mqtt.topics import AVAILABILITY, discovery, state_topic
from plant_control_addon.mqtt.transport import BrokerConfig
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
    tank = await registry.create_item(
        "tank",
        TankType(name="Бак", **SIMPLE["tank"]),
    )
    pump = await registry.create_item(
        "pump",
        PumpModel(
            name="Насос",
            flow=SIMPLE["pump"]["flow"],
            max_runtime_s=SIMPLE["pump"]["max_runtime_s"],
        ),
    )
    config = {
        "name": SIMPLE["name"],
        "tank_type": tank,
        "pump": {"model": pump, "entity_id": SIMPLE["pump"]["entity_id"]},
        "plumbing": SIMPLE["plumbing"],
        "flow_mode": "advanced",
        "routes": SIMPLE["routes"],
    }
    await registry.create(MachineConfig.model_validate(config))
    yield registry


@pytest.fixture
def board() -> ProblemBoard:
    return ProblemBoard()


@pytest.fixture
def controller(registry: MachineRegistry, gateway: FakeGateway) -> Controller:
    return Controller(registry, gateway, clock=SystemClock())


@pytest.fixture
def bridge(registry: MachineRegistry, board: ProblemBoard, controller: Controller) -> MqttBridge:
    return MqttBridge(lambda: None, registry, controller, board)


async def wait_idle(controller: Controller, machine_id: str) -> None:
    """Очередь в тесте разбираем руками: фоновая задача здесь не запущена."""
    controller.queue.dispatch()
    for _ in range(500):
        if not controller.is_busy(machine_id):
            return
        await asyncio.sleep(0.005)
    raise AssertionError("machine is still busy")


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


async def test_renamed_machine_is_announced_again(
    bridge: MqttBridge, registry: MachineRegistry
) -> None:
    session = FakeSession()
    entry = entry_of(registry)
    await bridge.publish_all(session)
    topic, _ = discovery(entry, "homeassistant")[0]

    config = entry.config.model_copy(deep=True)
    config.name = "Новое имя"
    await registry.update(entry.id, config)
    session.published.clear()
    await bridge.publish_all(session)

    device = session.last(topic)["device"]
    assert isinstance(device, dict) and device["name"] == "Новое имя"
    # Все описания с новым именем, без лишних повторов.
    assert len(session.topics()) == len(discovery(entry_of(registry), "homeassistant")) + 1


async def test_deleted_machine_entities_are_removed(
    bridge: MqttBridge, registry: MachineRegistry
) -> None:
    session = FakeSession()
    entry = entry_of(registry)
    topics = [topic for topic, _ in discovery(entry, "homeassistant")]
    await bridge.publish_all(session)

    await registry.delete(entry.id)
    session.published.clear()
    await bridge.publish_all(session)

    cleared = {topic for topic, payload, retain in session.published if payload == "" and retain}
    assert cleared == {*topics, state_topic(entry.id)}


async def test_leftovers_at_the_broker_are_removed(
    bridge: MqttBridge, registry: MachineRegistry
) -> None:
    """Описания с прошлых запусков: удалённая машина и удалённое растение."""
    session = FakeSession()
    entry = entry_of(registry)
    await bridge._known.add(["m-old"])
    await bridge.publish_all(session)
    own, own_body = discovery(entry, "homeassistant")[0]
    body = json.dumps(own_body)
    stale = "homeassistant/button/plant_control_m-old/water_main/config"
    old_plant = f"homeassistant/button/plant_control_{entry.id}/water_gone/config"
    foreign = "homeassistant/sensor/0x00158d/temperature/config"
    session.published.clear()

    for topic in (stale, old_plant, foreign, own):
        await bridge.handle_discovery(session, topic, body)
    # Пустое сообщение - это уже удалённая сущность.
    await bridge.handle_discovery(session, stale, "")
    # Машина другого экземпляра PlantControl на том же брокере: не наша, не трогаем.
    await bridge.handle_discovery(
        session, "homeassistant/button/plant_control_m-other/water_main/config", body
    )

    assert session.published == [
        (stale, "", True),
        (state_topic("m-old"), "", True),
        (old_plant, "", True),
    ]


async def test_known_machines_start_from_journals(tmp_path: Path) -> None:
    store = MachineStore(tmp_path / "known.db")
    await store.open()
    await store.save_calibration("m-gone", "main", "marks", "{}")
    known = KnownMachines(store)

    await known.load(["m-live"])

    assert "m-gone" in known and "m-live" in known and "m-other" not in known
    again = KnownMachines(store)
    await again.load([])
    assert "m-gone" in again


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
    bridge: MqttBridge, registry: MachineRegistry, controller: Controller, gateway: FakeGateway
) -> None:
    entry = entry_of(registry)
    entry.machine.tank.fill_full()
    before = entry.machine.tank.volume_ml

    await bridge.handle_command(f"plant_control/{entry.id}/cmd/water/main", "PRESS")
    await wait_idle(controller, entry.id)

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
    assert session.subscriptions == ["plant_control/+/cmd/#", "homeassistant/+/+/+/config"]


async def test_resolve_broker_falls_back_to_settings() -> None:
    from plant_control_addon.mqtt.transport import resolve_broker

    empty = Settings(_env_file=None)  # type: ignore[call-arg]
    assert await resolve_broker(empty) is None

    configured = Settings(_env_file=None, mqtt_host="core-mosquitto", mqtt_user="pc")  # type: ignore[call-arg]
    broker = await resolve_broker(configured)
    assert broker is not None
    assert (broker.host, broker.port, broker.username) == ("core-mosquitto", 1883, "pc")


# --- Настройки MQTT и переподключение ---


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def load_setting(self, key: str) -> str | None:
        return self.values.get(key)

    async def save_setting(self, key: str, value_json: str) -> None:
        self.values[key] = value_json


class Rig:
    """Менеджер MQTT с поддельными брокерами: каждое подключение даёт свою сессию."""

    def __init__(
        self,
        registry: MachineRegistry,
        controller: Controller,
        board: ProblemBoard,
        auto: BrokerConfig | None = None,
    ) -> None:
        self.store = MemoryStore()
        self.sessions: list[tuple[BrokerConfig, FakeSession]] = []
        self.auto = auto

        def make_bridge(broker: BrokerConfig, prefix: str) -> MqttBridge:
            @asynccontextmanager
            async def connect() -> AsyncIterator[FakeSession]:
                session = FakeSession()
                self.sessions.append((broker, session))
                yield session

            return MqttBridge(connect, registry, controller, board, discovery_prefix=prefix)

        async def auto_broker() -> BrokerConfig | None:
            return self.auto

        self.manager = MqttManager(self.store, auto_broker, make_bridge)


async def settle(manager: MqttManager) -> None:
    for _ in range(100):
        if manager.status().state == "connected":
            return
        await asyncio.sleep(0.01)


async def test_auto_broker_connects(
    registry: MachineRegistry, controller: Controller, board: ProblemBoard
) -> None:
    rig = Rig(registry, controller, board, auto=BrokerConfig("core-mosquitto", source="supervisor"))
    await rig.manager.load()
    await settle(rig.manager)

    status = rig.manager.status()
    assert (status.state, status.source, status.broker) == (
        "connected",
        "supervisor",
        "core-mosquitto:1883",
    )
    await rig.manager.stop()


async def test_no_broker_and_disabled_states(
    registry: MachineRegistry, controller: Controller, board: ProblemBoard
) -> None:
    rig = Rig(registry, controller, board)
    await rig.manager.load()
    assert rig.manager.status().state == "no_broker"

    await rig.manager.update(MqttSettingsIn(enabled=False))
    assert rig.manager.status().state == "off"
    assert rig.sessions == []


async def test_manual_broker_reconnects_and_keeps_password(
    registry: MachineRegistry, controller: Controller, board: ProblemBoard
) -> None:
    rig = Rig(registry, controller, board, auto=BrokerConfig("core-mosquitto"))
    await rig.manager.load()
    await settle(rig.manager)
    first = rig.sessions[0][1]

    await rig.manager.update(
        MqttSettingsIn(mode="manual", host="10.0.0.5", port=1884, username="pc", password="secret")
    )
    await settle(rig.manager)
    # Старый мост объявил машины недоступными, новый подключился к своему брокеру.
    assert (AVAILABILITY, "offline", True) in first.published
    broker, _ = rig.sessions[-1]
    assert (broker.host, broker.port, broker.username, broker.password) == (
        "10.0.0.5",
        1884,
        "pc",
        "secret",
    )

    # Пароль не передан - остаётся прежний, а наружу не отдаётся вовсе.
    saved = await rig.manager.update(
        MqttSettingsIn(mode="manual", host="10.0.0.5", port=1884, username="pc")
    )
    assert saved.password == "secret"
    assert "password" not in saved.public().model_dump()
    assert saved.public().has_password is True
    await rig.manager.stop()


async def test_mqtt_api(api: httpx.AsyncClient) -> None:
    # В тестовом приложении MQTT запрещён целиком: состояние "выключен".
    assert (await api.get("/api/mqtt/status")).json()["state"] == "off"
    saved = await api.put(
        "/api/mqtt/settings", json={"mode": "manual", "host": "broker", "password": "x"}
    )
    assert saved.status_code == 200
    body = (await api.get("/api/mqtt/settings")).json()
    assert body["host"] == "broker"
    assert body["has_password"] is True
    assert "password" not in body
    bad = await api.put("/api/mqtt/settings", json={"port": 70000})
    assert bad.status_code == 422
