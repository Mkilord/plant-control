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
from plant_control_addon.settings import Settings


class FakeGateway:
    """Поддельный клиент HA: помнит вызовы сервисов и умеет присылать события."""

    def __init__(self) -> None:
        self.is_connected = True
        self.states = [
            EntityState("switch.pump_1", "off", "Pump 1"),
            EntityState("switch.pump_2", "off", "Pump 2"),
            EntityState("sensor.temperature", "21", "Temperature"),
            EntityState("input_boolean.test_valve", "on", "Test valve"),
            # Клапаны коллектора из тестов: без них полив был бы запрещён.
            EntityState("input_boolean.valve_1", "off", "Valve 1"),
            EntityState("input_boolean.valve_2", "off", "Valve 2"),
            EntityState("input_boolean.valve_3", "off", "Valve 3"),
            EntityState("input_boolean.valve_4", "off", "Valve 4"),
        ]
        self.calls: list[tuple[str, str, str]] = []
        self.offline = False
        self.state_listeners: list[StateListener] = []
        self.connect_listeners: list[ConnectListener] = []
        self.notifications: list[dict[str, Any]] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        # Телефоны с приложением HA: на них уходят пуши.
        self.services: dict[str, dict[str, Any]] = {
            "notify": {"mobile_app_phone": {}, "notify": {}, "persistent_notification": {}},
            "switch": {"turn_on": {}, "turn_off": {}},
        }

    async def get_states(self) -> list[EntityState]:
        if self.offline:
            raise HomeAssistantUnavailableError("offline")
        return self.states

    async def get_services(self) -> dict[str, dict[str, Any]]:
        if self.offline:
            raise HomeAssistantUnavailableError("offline")
        return self.services

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


def settings(**values: object) -> Settings:
    """Настройки для тестов: .env разработчика не читается, иначе тесты зависят от машины."""
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


AppFactory = Callable[[], Any]


@pytest.fixture
async def api(gateway: FakeGateway, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        ha=gateway, settings=settings(), data_dir=tmp_path, watchdog_interval=0.05, mqtt=False
    )
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


async def legacy(api: httpx.AsyncClient, old: dict[str, Any]) -> dict[str, Any]:
    """Машина в старом формате (бак и насос внутри) -> новый формат со ссылками.

    Записи справочников создаются через API. Одинаковые настройки дают одну запись,
    как при миграции: так правка машины без изменения насоса не меняет его id.
    """
    import json

    if "tank_type" in old:
        return old
    cache: dict[tuple[str, str], str] = api.__dict__.setdefault("_catalog_cache", {})

    async def item(kind: str, body: dict[str, Any]) -> str:
        key = (kind, json.dumps(body, sort_keys=True))
        if key not in cache:
            response = await api.post(f"/api/catalog/{kind}", json=body)
            assert response.status_code == 201, response.text
            cache[key] = response.json()["id"]
        return cache[key]

    tank = old["tank"]
    pump = old["pump"]
    new: dict[str, Any] = {
        "name": old["name"],
        "tank_type": await item(
            "tank",
            {"name": "Бак", "geometry": tank["geometry"], "reserve_ml": tank.get("reserve_ml", 0)},
        ),
        "pump": {
            "model": await item(
                "pump",
                {
                    "name": "Насос",
                    "flow": pump.get("flow"),
                    "max_runtime_s": pump.get("max_runtime_s", 300),
                    "cooldown_s": pump.get("cooldown_s", 0),
                },
            ),
            "entity_id": pump["entity_id"],
        },
        "plumbing": dict(old["plumbing"]),
        "routes": old["routes"],
    }
    for key in ("head_model", "base_route"):
        if key in old:
            new[key] = old[key]
    new["flow_mode"] = old.get("flow_mode", "advanced")
    if old["plumbing"]["type"] == "collector":
        timings = old.get("timings") or {}
        new["plumbing"]["collector_type"] = await item(
            "collector",
            {
                "name": "Коллектор",
                "outlets": max(2, len(old["routes"])),
                "valve_lead_s": timings.get("valve_lead_s", 0.5),
                "valve_lag_s": timings.get("valve_lag_s", 0.5),
            },
        )
    if old.get("power_group"):
        new["power_group"] = await item(
            "power",
            {
                "name": old["power_group"],
                "max_concurrent": old.get("power_limit", 1),
                "min_start_gap_s": old.get("power_gap_s", 2),
            },
        )
    return new
