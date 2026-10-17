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
from plant_control_addon.mqtt.known import KnownMachines
from plant_control_addon.mqtt.state import state_payload
from plant_control_addon.mqtt.topics import AVAILABILITY, ROOT, discovery, state_topic
from plant_control_addon.registry import MachineRegistry

log = logging.getLogger(__name__)

# Узел наших сущностей в темах discovery: <prefix>/<компонент>/plant_control_<машина>/<id>/config.
NODE_PREFIX = f"{ROOT}_"

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
        known: KnownMachines | None = None,
    ) -> None:
        self._factory = session_factory
        self._registry = registry
        self._controller = controller
        self._board = board
        self._prefix = discovery_prefix
        self._interval = publish_interval
        self._reconnect_delay = reconnect_delay
        # Что сейчас лежит у брокера: машина -> {тема discovery: описание}.
        self._published: dict[str, dict[str, str]] = {}
        # Машины, которые публиковал этот add-on: чужие сущности на брокере не трогаем.
        self._known = known or KnownMachines()
        self.connected = False
        # Последняя ошибка соединения: интерфейс показывает, почему нет связи.
        self.last_error: str | None = None

    # --- Жизненный цикл ---

    async def run(self) -> None:
        """Фоновая задача: держит соединение и переподключается при обрыве."""
        while True:
            try:
                async with self._factory() as session:
                    self.connected = True
                    self.last_error = None
                    try:
                        await self._on_connect(session)
                        await self._serve(session)
                    except asyncio.CancelledError:
                        # Мост остановили (выключили MQTT, сменили брокер): сущности
                        # машин в HA должны стать недоступными, а не висеть "в сети".
                        with contextlib.suppress(Exception):
                            await asyncio.wait_for(
                                session.publish(AVAILABILITY, OFFLINE, retain=True), 2
                            )
                        raise
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning("mqtt connection failed: %s", error)
                self.last_error = str(error) or type(error).__name__
            finally:
                self.connected = False
                self._published.clear()
            await asyncio.sleep(self._reconnect_delay)

    async def _serve(self, session: MqttSession) -> None:
        publisher = asyncio.create_task(self._publish_loop(session))
        try:
            async for topic, payload in session.messages():
                try:
                    if topic.endswith("/config"):
                        await self.handle_discovery(session, topic, payload)
                        continue
                    await self.handle_command(topic, payload)
                except Exception:
                    log.exception("mqtt command %s failed", topic)
        finally:
            publisher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await publisher

    async def _on_connect(self, session: MqttSession) -> None:
        await self._known.load(entry.id for entry in self._registry.entries())
        await session.publish(AVAILABILITY, ONLINE, retain=True)
        await session.subscribe(f"{ROOT}/+/cmd/#")
        await self.publish_all(session)
        # Описания у брокера, в том числе с прошлых запусков: по ним видно,
        # что осталось от удалённых машин и растений. Подписка после публикации,
        # чтобы свои свежие описания не приняли за лишние.
        await session.subscribe(f"{self._prefix}/+/+/+/config")

    async def _publish_loop(self, session: MqttSession) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.publish_all(session)
            except Exception:
                log.exception("mqtt publish failed")

    # --- Публикация ---

    async def publish_all(self, session: MqttSession) -> None:
        """Описания машин и текущее состояние всех.

        Описание публикуется заново, если поменялось (переименовали машину или
        растение). Сущности удалённых машин и растений убираются из HA пустым
        сообщением в их тему discovery.
        """
        alive = {entry.id for entry in self._registry.entries()}
        await self._known.add(alive)
        for entry in self._registry.entries():
            wanted = {
                topic: json.dumps(body, ensure_ascii=False)
                for topic, body in discovery(entry, self._prefix)
            }
            before = self._published.get(entry.id, {})
            for topic, body in wanted.items():
                if before.get(topic) != body:
                    await session.publish(topic, body, retain=True)
            for topic in before.keys() - wanted.keys():
                await session.publish(topic, "", retain=True)
            self._published[entry.id] = wanted
            payload = state_payload(entry, self._board.for_machine(entry.id))
            await session.publish(
                state_topic(entry.id), json.dumps(payload, ensure_ascii=False), retain=True
            )
        for machine_id in list(self._published.keys() - alive):
            await self._remove_machine(session, machine_id, self._published.pop(machine_id))

    async def handle_discovery(self, session: MqttSession, topic: str, payload: str) -> None:
        """Описание сущности у брокера: лишнее (удалённая машина или растение) убрать."""
        if not payload:
            return
        parts = topic.split("/")
        if len(parts) != 5 or parts[0] != self._prefix or not parts[2].startswith(NODE_PREFIX):
            return
        machine_id = parts[2].removeprefix(NODE_PREFIX)
        if topic in self._published.get(machine_id, {}):
            return
        if machine_id in {entry.id for entry in self._registry.entries()}:
            if machine_id not in self._published:
                # Машину только что создали, её описания ещё не ушли.
                return
            log.info("removing stale Home Assistant entity %s", topic)
            await session.publish(topic, "", retain=True)
            return
        if machine_id not in self._known:
            # Машина другого экземпляра PlantControl на том же брокере.
            return
        log.info("removing Home Assistant entity of deleted machine %s", topic)
        await session.publish(topic, "", retain=True)
        await session.publish(state_topic(machine_id), "", retain=True)

    async def _remove_machine(
        self, session: MqttSession, machine_id: str, topics: dict[str, str]
    ) -> None:
        log.info("removing Home Assistant entities of deleted machine %s", machine_id)
        for topic in topics:
            await session.publish(topic, "", retain=True)
        await session.publish(state_topic(machine_id), "", retain=True)

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
