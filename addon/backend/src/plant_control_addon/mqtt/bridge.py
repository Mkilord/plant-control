"""Мост в Home Assistant через MQTT.

Публикует описания сущностей (discovery), состояние машин и слушает команды:
кнопки "Полить" и "Бак залит", поле дозы. Кнопка "Бак залит" нужна для метки NFC:
метка запускает автоматизацию, автоматизация нажимает кнопку.

Брокер и клиент спрятаны за протоколом сессии, поэтому мост проверяется тестами
без реального MQTT.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

from plant_control.domain.problems import ProblemBoard

from plant_control_addon.controller import Controller
from plant_control_addon.mqtt.state import state_payload
from plant_control_addon.mqtt.topics import AVAILABILITY, ROOT, discovery, state_topic
from plant_control_addon.registry import MachineRegistry

log = logging.getLogger(__name__)

ONLINE = "online"
OFFLINE = "offline"


class MqttSession(Protocol):
    """Одно живое соединение с брокером."""

    async def publish(self, topic: str, payload: str, retain: bool = False) -> None: ...

    async def subscribe(self, topic: str) -> None: ...

    def messages(self) -> AsyncIterator[tuple[str, str]]: ...


# Фабрика соединений: асинхронный контекст, внутри которого живёт сессия.
SessionFactory = Callable[[], Any]


class MqttBridge:
    def __init__(
        self,
        session_factory: SessionFactory,
        registry: MachineRegistry,
        controller: Controller,
        board: ProblemBoard,
        *,
        discovery_prefix: str = "homeassistant",
        publish_interval: float = 10.0,
        reconnect_delay: float = 5.0,
    ) -> None:
        self._factory = session_factory
        self._registry = registry
        self._controller = controller
        self._board = board
        self._prefix = discovery_prefix
        self._interval = publish_interval
        self._reconnect_delay = reconnect_delay
        self._announced: set[str] = set()
        self.connected = False

    # --- Жизненный цикл ---

    async def run(self) -> None:
        """Фоновая задача: держит соединение и переподключается при обрыве."""
        while True:
            try:
                async with self._factory() as session:
                    self.connected = True
                    await self._on_connect(session)
                    await self._serve(session)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning("mqtt connection failed: %s", error)
            finally:
                self.connected = False
                self._announced.clear()
            await asyncio.sleep(self._reconnect_delay)

    async def _serve(self, session: MqttSession) -> None:
        publisher = asyncio.create_task(self._publish_loop(session))
        try:
            async for topic, payload in session.messages():
                try:
                    await self.handle_command(topic, payload)
                except Exception:
                    log.exception("mqtt command %s failed", topic)
        finally:
            publisher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await publisher

    async def _on_connect(self, session: MqttSession) -> None:
        await session.publish(AVAILABILITY, ONLINE, retain=True)
        await session.subscribe(f"{ROOT}/+/cmd/#")
        await self.publish_all(session)

    async def _publish_loop(self, session: MqttSession) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.publish_all(session)
            except Exception:
                log.exception("mqtt publish failed")

    # --- Публикация ---

    async def publish_all(self, session: MqttSession) -> None:
        """Описания новых машин и текущее состояние всех."""
        for entry in self._registry.entries():
            if entry.id not in self._announced:
                for topic, body in discovery(entry, self._prefix):
                    await session.publish(topic, json.dumps(body, ensure_ascii=False), retain=True)
                self._announced.add(entry.id)
            payload = state_payload(entry, self._board.for_machine(entry.id))
            await session.publish(
                state_topic(entry.id), json.dumps(payload, ensure_ascii=False), retain=True
            )

    # --- Команды ---

    async def handle_command(self, topic: str, payload: str) -> None:
        """Тема вида plant_control/<машина>/cmd/<команда>[/<растение>]."""
        parts = topic.split("/")
        if len(parts) < 4 or parts[0] != ROOT or parts[2] != "cmd":
            return
        machine_id, command = parts[1], parts[3]
        route_id = parts[4] if len(parts) > 4 else ""

        if command == "tank_filled":
            await self._controller.refill(machine_id, None)
            log.info("tank of %s marked as full from Home Assistant", machine_id)
        elif command == "water":
            entry = self._registry.entry(machine_id)
            dose = self._dose(machine_id, route_id)
            await self._controller.start_watering(
                machine_id, route_id or entry.config.routes[0].id, dose
            )
        elif command == "dose":
            await self._registry.set_route_dose(machine_id, route_id, float(payload))
        else:
            log.debug("unknown mqtt command %s", topic)

    def _dose(self, machine_id: str, route_id: str) -> float:
        config = self._registry.entry(machine_id).config
        for route in config.routes:
            if not route_id or route.id == route_id:
                return route.default_dose_ml
        return config.routes[0].default_dose_ml
