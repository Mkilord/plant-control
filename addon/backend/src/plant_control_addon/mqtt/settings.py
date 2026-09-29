"""Настройки MQTT из интерфейса и управление мостом на ходу.

Брокер можно взять автоматически (его выдаёт Supervisor, обычно это add-on
Mosquitto) или ввести вручную. Настройки лежат в базе, при сохранении мост
переподключается к новому брокеру без перезапуска add-on'а.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from plant_control_addon.mqtt.bridge import MqttBridge
from plant_control_addon.mqtt.transport import BrokerConfig

log = logging.getLogger(__name__)

SETTINGS_KEY = "mqtt"


class MqttSettings(BaseModel):
    enabled: bool = True
    # auto - брокер из Home Assistant, manual - свой адрес.
    mode: Literal["auto", "manual"] = "auto"
    host: str = Field(default="", max_length=255)
    port: int = Field(default=1883, ge=1, le=65535)
    username: str = Field(default="", max_length=255)
    password: str = Field(default="", max_length=255)
    # Префикс, по которому Home Assistant ищет описания сущностей.
    discovery_prefix: str = Field(default="homeassistant", min_length=1, pattern=r"^[\w/-]+$")

    def public(self) -> "MqttSettingsOut":
        """Для интерфейса: пароль не отдаётся, только признак, что он задан."""
        return MqttSettingsOut(
            **self.model_dump(exclude={"password"}), has_password=bool(self.password)
        )


class MqttSettingsOut(BaseModel):
    enabled: bool
    mode: Literal["auto", "manual"]
    host: str
    port: int
    username: str
    has_password: bool
    discovery_prefix: str


class MqttSettingsIn(BaseModel):
    """Правка из интерфейса. password None - оставить прежний."""

    enabled: bool = True
    mode: Literal["auto", "manual"] = "auto"
    host: str = Field(default="", max_length=255)
    port: int = Field(default=1883, ge=1, le=65535)
    username: str = Field(default="", max_length=255)
    password: str | None = Field(default=None, max_length=255)
    discovery_prefix: str = Field(default="homeassistant", min_length=1, pattern=r"^[\w/-]+$")

    def merge(self, current: MqttSettings) -> MqttSettings:
        data = self.model_dump(exclude={"password"})
        password = current.password if self.password is None else self.password
        return MqttSettings(**data, password=password)


MqttState = Literal["off", "no_broker", "connecting", "connected", "error"]


class MqttStatus(BaseModel):
    state: MqttState
    # Откуда брокер: supervisor, env, manual. Пусто - брокера нет.
    source: str = ""
    broker: str = ""
    error: str | None = None


class SettingsStore(Protocol):
    async def load_setting(self, key: str) -> str | None: ...

    async def save_setting(self, key: str, value_json: str) -> None: ...


# Найти брокер в режиме "автоматически".
AutoBroker = Callable[[], Awaitable[BrokerConfig | None]]
# Собрать мост к брокеру.
BridgeFactory = Callable[[BrokerConfig, str], MqttBridge]


class MqttManager:
    """Держит мост в HA и пересоздаёт его, когда меняются настройки."""

    def __init__(
        self,
        store: SettingsStore,
        auto_broker: AutoBroker,
        bridge_factory: BridgeFactory,
        *,
        allowed: bool = True,
    ) -> None:
        self._store = store
        self._auto_broker = auto_broker
        self._bridge_factory = bridge_factory
        # allowed False - MQTT выключен целиком (тесты, отладка).
        self._allowed = allowed
        self.current = MqttSettings()
        self.bridge: MqttBridge | None = None
        self._task: asyncio.Task[None] | None = None
        self._broker: BrokerConfig | None = None
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        raw = await self._store.load_setting(SETTINGS_KEY)
        if raw is not None:
            try:
                self.current = MqttSettings.model_validate_json(raw)
            except ValueError:
                log.exception("stored mqtt settings are broken, using defaults")
        await self._restart()

    async def update(self, change: MqttSettingsIn) -> MqttSettings:
        settings = change.merge(self.current)
        await self._store.save_setting(SETTINGS_KEY, settings.model_dump_json())
        self.current = settings
        await self._restart()
        return settings

    def status(self) -> MqttStatus:
        if not self._allowed or not self.current.enabled:
            return MqttStatus(state="off")
        broker = self._broker
        if broker is None:
            return MqttStatus(state="no_broker")
        address = f"{broker.host}:{broker.port}"
        bridge = self.bridge
        if bridge is not None and bridge.connected:
            return MqttStatus(state="connected", source=broker.source, broker=address)
        if bridge is not None and bridge.last_error:
            return MqttStatus(
                state="error", source=broker.source, broker=address, error=bridge.last_error
            )
        return MqttStatus(state="connecting", source=broker.source, broker=address)

    async def stop(self) -> None:
        async with self._lock:
            await self._stop()

    async def _restart(self) -> None:
        async with self._lock:
            await self._stop()
            self._broker = None
            if not self._allowed or not self.current.enabled:
                log.info("mqtt is off")
                return
            broker = await self._resolve()
            if broker is None:
                log.info("mqtt is off: no broker")
                return
            log.info("mqtt broker %s:%s (%s)", broker.host, broker.port, broker.source)
            self._broker = broker
            self.bridge = self._bridge_factory(broker, self.current.discovery_prefix)
            self._task = asyncio.create_task(self.bridge.run(), name="mqtt-bridge")

    async def _resolve(self) -> BrokerConfig | None:
        settings = self.current
        if settings.mode == "manual":
            if not settings.host.strip():
                return None
            return BrokerConfig(
                host=settings.host.strip(),
                port=settings.port,
                username=settings.username,
                password=settings.password,
                source="manual",
            )
        return await self._auto_broker()

    async def _stop(self) -> None:
        task, self._task = self._task, None
        self.bridge = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
