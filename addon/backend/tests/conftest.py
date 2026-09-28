"""Общие фикстуры: поддельный HA и приложение с временной базой."""

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from plant_control_addon.api.app import create_app
from plant_control_addon.ha.client import (
    ConnectListener,
    EntityState,
    HomeAssistantUnavailableError,
    StateListener,
)


class FakeGateway:
    """Поддельный клиент HA: помнит вызовы сервисов и умеет присылать события."""

    def __init__(self) -> None:
        self.is_connected = True
        self.states = [
            EntityState("switch.pump_1", "off", "Pump 1"),
            EntityState("switch.pump_2", "off", "Pump 2"),
            EntityState("sensor.temperature", "21", "Temperature"),
            EntityState("input_boolean.test_valve", "on", "Test valve"),
        ]
        self.calls: list[tuple[str, str, str]] = []
        self.offline = False
        self.state_listeners: list[StateListener] = []
        self.connect_listeners: list[ConnectListener] = []
        self.notifications: list[dict[str, Any]] = []
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def get_states(self) -> list[EntityState]:
        if self.offline:
            raise HomeAssistantUnavailableError("offline")
        return self.states

    async def call_service(self, domain: str, service: str, entity_id: str) -> None:
        if self.offline:
            raise HomeAssistantUnavailableError("offline")
        self.calls.append((domain, service, entity_id))

    async def call_service_data(self, domain: str, service: str, data: dict[str, Any]) -> None:
        if self.offline:
            raise HomeAssistantUnavailableError("offline")
        self.notifications.append({"service": f"{domain}.{service}", **data})

    async def fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        if self.offline:
            raise HomeAssistantUnavailableError("offline")
        self.events.append((event_type, data))

    def add_state_listener(self, listener: StateListener) -> None:
        self.state_listeners.append(listener)

    def add_connect_listener(self, listener: ConnectListener) -> None:
        self.connect_listeners.append(listener)

    def emit(self, entity_id: str, state: str) -> None:
        for listener in self.state_listeners:
            listener(entity_id, EntityState(entity_id, state, entity_id))

    def commands(self) -> list[str]:
        """Вызовы в коротком виде: 'turn_on switch.pump_1'."""
        return [f"{service} {entity}" for _, service, entity in self.calls]


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


AppFactory = Callable[[], Any]


@pytest.fixture
async def api(gateway: FakeGateway, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(ha=gateway, data_dir=tmp_path, watchdog_interval=0.05, mqtt=False)
    async with running(app) as client:
        yield client


class running:
    """Запускает приложение со стартом и остановкой (lifespan) и даёт HTTP-клиент."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._lifespan: Any = None
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> httpx.AsyncClient:
        self._lifespan = self._app.router.lifespan_context(self._app)
        await self._lifespan.__aenter__()
        transport = httpx.ASGITransport(app=self._app)
        self._client = httpx.AsyncClient(transport=transport, base_url="http://test")
        return self._client

    async def __aexit__(self, *exc: object) -> None:
        assert self._client is not None
        await self._client.aclose()
        await self._lifespan.__aexit__(None, None, None)
