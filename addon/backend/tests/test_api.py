"""Тесты эндпоинтов HA и health."""

import os
from pathlib import Path

import httpx

from plant_control_addon.api.app import create_app
from tests.conftest import FakeGateway, running, settings


async def test_health(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/health")
    assert response.json() == {"status": "ok", "home_assistant": "connected", "machines": 0}


async def test_lists_only_switchable_entities_sorted(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/ha/entities")
    assert response.status_code == 200
    assert [e["entity_id"] for e in response.json()] == [
        "input_boolean.test_valve",
        "input_boolean.valve_1",
        "input_boolean.valve_2",
        "input_boolean.valve_3",
        "input_boolean.valve_4",
        "switch.pump_1",
        "switch.pump_2",
    ]


async def test_turn_on(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    response = await api.post("/api/ha/entities/switch.pump_2/turn_on")
    assert response.status_code == 204
    assert gateway.calls == [("switch", "turn_on", "switch.pump_2")]


async def test_cannot_switch_sensor(api: httpx.AsyncClient) -> None:
    response = await api.post("/api/ha/entities/sensor.temperature/turn_on")
    assert response.status_code == 400


async def test_ha_offline_gives_503(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    gateway.offline = True
    response = await api.get("/api/ha/entities")
    assert response.status_code == 503


async def test_frontend_is_served_when_built(gateway: FakeGateway, tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>plant control</html>", encoding="utf-8")
    os.environ["PLANT_CONTROL_STATIC_DIR"] = str(static)
    try:
        app = create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    finally:
        del os.environ["PLANT_CONTROL_STATIC_DIR"]
    async with running(app) as client:
        page = await client.get("/")
        health = await client.get("/api/health")
    assert "plant control" in page.text
    assert health.status_code == 200
