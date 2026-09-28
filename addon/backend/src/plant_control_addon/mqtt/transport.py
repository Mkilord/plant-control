"""Настоящее соединение с брокером MQTT.

Внутри add-on'а адрес и пароль брокера выдаёт Supervisor: add-on не знает их
заранее, а спрашивает по внутреннему адресу. При разработке те же данные
берутся из настроек (.env).

Всё, что связано с библиотекой aiomqtt, живёт только здесь: мост знает лишь
протокол сессии.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

import aiohttp
import aiomqtt

from plant_control_addon.mqtt.bridge import OFFLINE, MqttSession
from plant_control_addon.mqtt.topics import AVAILABILITY
from plant_control_addon.settings import Settings

log = logging.getLogger(__name__)

SUPERVISOR_MQTT_URL = "http://supervisor/services/mqtt"
CLIENT_ID = "plant-control"


@dataclass(frozen=True, slots=True)
class BrokerConfig:
    host: str
    port: int = 1883
    username: str = ""
    password: str = ""


async def resolve_broker(settings: Settings) -> BrokerConfig | None:
    """Данные брокера: сначала Supervisor, потом настройки. None - брокера нет."""
    if settings.supervisor_token:
        broker = await _ask_supervisor(settings.supervisor_token)
        if broker is not None:
            return broker
    if not settings.mqtt_host:
        return None
    return BrokerConfig(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        username=settings.mqtt_user,
        password=settings.mqtt_password,
    )


async def _ask_supervisor(token: str) -> BrokerConfig | None:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with (
            aiohttp.ClientSession(timeout=timeout, headers=headers) as session,
            session.get(SUPERVISOR_MQTT_URL) as response,
        ):
            if response.status != 200:
                log.info("supervisor has no mqtt service (http %s)", response.status)
                return None
            body = await response.json()
    except Exception as error:
        log.warning("cannot ask supervisor about mqtt: %s", error)
        return None

    data = body.get("data") or {}
    host = str(data.get("host") or "")
    if not host:
        return None
    return BrokerConfig(
        host=host,
        port=int(data.get("port") or 1883),
        username=str(data.get("username") or ""),
        password=str(data.get("password") or ""),
    )


class AiomqttSession:
    """Обёртка над клиентом aiomqtt под протокол MqttSession."""

    def __init__(self, client: aiomqtt.Client) -> None:
        self._client = client

    async def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        await self._client.publish(topic, payload, retain=retain)

    async def subscribe(self, topic: str) -> None:
        await self._client.subscribe(topic)

    async def messages(self) -> AsyncIterator[tuple[str, str]]:
        async for message in self._client.messages:
            payload = message.payload
            text = payload.decode() if isinstance(payload, bytes | bytearray) else str(payload)
            yield str(message.topic), text


def session_factory(
    broker: BrokerConfig,
) -> Callable[[], AbstractAsyncContextManager[MqttSession]]:
    """Фабрика соединений для моста: каждый вызов - новая попытка подключиться."""

    @asynccontextmanager
    async def connect() -> AsyncIterator[MqttSession]:
        # Последняя воля: если add-on упадёт, брокер сам объявит нас офлайн.
        async with aiomqtt.Client(
            hostname=broker.host,
            port=broker.port,
            username=broker.username or None,
            password=broker.password or None,
            identifier=CLIENT_ID,
            will=aiomqtt.Will(topic=AVAILABILITY, payload=OFFLINE, retain=True),
        ) as client:
            yield AiomqttSession(client)

    return connect
