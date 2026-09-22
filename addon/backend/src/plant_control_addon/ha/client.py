"""Клиент WebSocket API Home Assistant.

Протокол:
1. HA присылает auth_required, клиент отвечает токеном, HA присылает auth_ok.
2. Каждая команда идёт с уникальным id, ответ приходит с тем же id.
3. Подписка на события: ответ-подтверждение, затем события с id подписки.

Клиент держит одно соединение и сам переподключается при обрыве.
Команды, отправленные во время обрыва, сразу получают HomeAssistantUnavailableError.
"""

import asyncio
import contextlib
import itertools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


class HomeAssistantError(Exception):
    pass


class HomeAssistantUnavailableError(HomeAssistantError):
    """Нет соединения с HA или он не ответил вовремя."""


class HomeAssistantAuthError(HomeAssistantError):
    """HA отклонил токен. Переподключение не поможет."""


class HomeAssistantCommandError(HomeAssistantError):
    """HA выполнил команду с ошибкой."""


@dataclass(frozen=True, slots=True)
class EntityState:
    entity_id: str
    state: str
    friendly_name: str

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    @classmethod
    def from_ha(cls, raw: dict[str, Any]) -> "EntityState":
        attributes = raw.get("attributes") or {}
        return cls(
            entity_id=raw["entity_id"],
            state=raw["state"],
            friendly_name=attributes.get("friendly_name") or raw["entity_id"],
        )


# Вызывается при каждой смене состояния: entity_id и новое состояние (None - сущность удалена).
StateListener = Callable[[str, EntityState | None], None]
# Вызывается после каждого успешного подключения (и переподключения).
ConnectListener = Callable[[], None]


class HomeAssistantClient:
    def __init__(
        self,
        url: str,
        token: str,
        *,
        command_timeout: float = 10.0,
        reconnect_delay: float = 5.0,
    ) -> None:
        self._url = url
        self._token = token
        self._command_timeout = command_timeout
        self._reconnect_delay = reconnect_delay
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._listeners: list[StateListener] = []
        self._connect_listeners: list[ConnectListener] = []
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._state_subscription_id: int | None = None
        self.auth_error: str | None = None

    # --- Жизненный цикл ---

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    async def start(self) -> None:
        """Запустить фоновое соединение. Не ждёт подключения."""
        if self._task is None:
            self._session = aiohttp.ClientSession()
            self._task = asyncio.create_task(self._run(), name="ha-websocket")

    async def wait_connected(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
        except TimeoutError:
            return False
        return True

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._session is not None:
            await self._session.close()
            self._session = None

    # --- Команды ---

    async def get_states(self) -> list[EntityState]:
        result = await self._command({"type": "get_states"})
        return [EntityState.from_ha(raw) for raw in result]

    async def call_service(self, domain: str, service: str, entity_id: str) -> None:
        await self._command(
            {
                "type": "call_service",
                "domain": domain,
                "service": service,
                "target": {"entity_id": entity_id},
            }
        )

    def add_state_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def add_connect_listener(self, listener: ConnectListener) -> None:
        self._connect_listeners.append(listener)

    # --- Внутреннее ---

    async def _command(self, payload: dict[str, Any]) -> Any:
        ws = self._ws
        if ws is None or not self.is_connected:
            raise HomeAssistantUnavailableError("not connected to Home Assistant")
        message_id = next(self._ids)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        try:
            await ws.send_json({"id": message_id, **payload})
            return await asyncio.wait_for(future, self._command_timeout)
        except TimeoutError:
            raise HomeAssistantUnavailableError(f"no answer to {payload['type']}") from None
        except (aiohttp.ClientError, ConnectionError) as error:
            raise HomeAssistantUnavailableError(str(error)) from error
        finally:
            self._pending.pop(message_id, None)

    async def _run(self) -> None:
        assert self._session is not None
        while True:
            try:
                async with self._session.ws_connect(self._url, heartbeat=30) as ws:
                    await self._authenticate(ws)
                    self._ws = ws
                    self._connected.set()
                    log.info("connected to Home Assistant")
                    self._notify_connected()
                    subscribe = asyncio.create_task(self._subscribe_states())
                    try:
                        await self._read_loop(ws)
                    finally:
                        subscribe.cancel()
            except HomeAssistantAuthError as error:
                log.error("Home Assistant rejected the token: %s", error)
                self.auth_error = str(error)
                self._disconnected()
                return
            except (aiohttp.ClientError, ConnectionError, TimeoutError, OSError) as error:
                log.warning("Home Assistant connection failed: %s", error)
            self._disconnected()
            await asyncio.sleep(self._reconnect_delay)

    async def _authenticate(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        hello = await ws.receive_json(timeout=self._command_timeout)
        if hello.get("type") != "auth_required":
            raise ConnectionError(f"unexpected greeting: {hello}")
        await ws.send_json({"type": "auth", "access_token": self._token})
        answer = await ws.receive_json(timeout=self._command_timeout)
        if answer.get("type") == "auth_invalid":
            raise HomeAssistantAuthError(answer.get("message", "invalid token"))
        if answer.get("type") != "auth_ok":
            raise ConnectionError(f"unexpected auth answer: {answer}")

    async def _subscribe_states(self) -> None:
        try:
            message_id = next(self._ids)
            future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
            self._pending[message_id] = future
            self._state_subscription_id = message_id
            assert self._ws is not None
            await self._ws.send_json(
                {"id": message_id, "type": "subscribe_events", "event_type": "state_changed"}
            )
            await asyncio.wait_for(future, self._command_timeout)
        except (HomeAssistantError, TimeoutError, aiohttp.ClientError) as error:
            log.warning("state subscription failed: %s", error)

    async def _read_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for message in ws:
            if message.type is not aiohttp.WSMsgType.TEXT:
                if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
                continue
            data = message.json()
            if data.get("type") == "result":
                self._resolve(data)
            elif data.get("type") == "event" and data.get("id") == self._state_subscription_id:
                self._dispatch_state(data["event"])

    def _resolve(self, data: dict[str, Any]) -> None:
        future = self._pending.pop(data.get("id", -1), None)
        if future is None or future.done():
            return
        if data.get("success"):
            future.set_result(data.get("result"))
        else:
            error = data.get("error") or {}
            future.set_exception(HomeAssistantCommandError(error.get("message", "command failed")))

    def _dispatch_state(self, event: dict[str, Any]) -> None:
        payload = event.get("data") or {}
        entity_id = payload.get("entity_id")
        if not entity_id:
            return
        raw = payload.get("new_state")
        state = EntityState.from_ha(raw) if raw else None
        for listener in self._listeners:
            try:
                listener(entity_id, state)
            except Exception:  # слушатель не должен ронять соединение
                log.exception("state listener failed")

    def _notify_connected(self) -> None:
        for listener in self._connect_listeners:
            try:
                listener()
            except Exception:
                log.exception("connect listener failed")

    def _disconnected(self) -> None:
        self._connected.clear()
        self._ws = None
        self._state_subscription_id = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(HomeAssistantUnavailableError("connection lost"))
        self._pending.clear()
