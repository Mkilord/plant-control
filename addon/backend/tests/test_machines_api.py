"""Тесты CRUD машин и действий."""

import asyncio
import copy
from pathlib import Path
from typing import Any

import httpx
import pytest

from plant_control_addon.api.app import create_app
from plant_control_addon.ha.client import EntityState
from tests.conftest import FakeGateway, running, settings

# Простая поливалка: бак 2 л (цилиндр 130 x 151 мм), 500 мл запаса,
# насос 1000 мл/с, чтобы поливы в тестах шли за доли секунды.
SIMPLE: dict[str, Any] = {
    "name": "Фикус",
    "tank": {
        "geometry": {"shape": "vertical_cylinder", "diameter_mm": 130, "height_mm": 151},
        "reserve_ml": 500,
    },
    "pump": {
        "entity_id": "switch.pump_1",
        "flow": {"model": "constant", "flow_ml_s": 1000},
        "max_runtime_s": 60,
        "cooldown_s": 0,
    },
    "plumbing": {"type": "direct", "back_to_tank_fraction": 0.0},
    "routes": [
        {
            "id": "main",
            "connection": {"length_mm": 700, "inner_diameter_mm": 4},
            "outlet_height_mm": 300,
        },
    ],
}

COLLECTOR: dict[str, Any] = {
    **SIMPLE,
    "name": "Коллектор",
    "plumbing": {"type": "collector", "supply": {"length_mm": 500, "inner_diameter_mm": 4}},
    "routes": [
        {
            "id": "v1",
            "valve_entity_id": "input_boolean.valve_1",
            "connection": {"length_mm": 300, "inner_diameter_mm": 4},
            "outlet_height_mm": 300,
        },
        {
            "id": "v2",
            "valve_entity_id": "input_boolean.valve_2",
            "connection": {"length_mm": 300, "inner_diameter_mm": 4},
            "outlet_height_mm": 300,
        },
    ],
    "timings": {"valve_lead_s": 0, "valve_lag_s": 0},
}


async def create(api: httpx.AsyncClient, config: dict[str, Any]) -> dict[str, Any]:
    response = await api.post("/api/machines", json=config)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def wait_idle(api: httpx.AsyncClient, machine_id: str) -> dict[str, Any]:
    for _ in range(200):
        body: dict[str, Any] = (await api.get(f"/api/machines/{machine_id}")).json()
        if not body["status"]["busy"]:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("machine is still busy")


# --- CRUD ---


async def test_create_machine(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    body = await create(api, SIMPLE)

    assert body["id"].startswith("m-")
    assert body["config"]["name"] == "Фикус"
    tank = body["status"]["tank"]
    assert tank["capacity_ml"] == pytest.approx(2004, abs=1)
    assert tank["usable_ml"] == pytest.approx(1504, abs=1)
    # Безопасный старт новой машины: насос выключен командой.
    assert gateway.commands() == ["turn_off switch.pump_1"]


async def test_list_and_get(api: httpx.AsyncClient) -> None:
    body = await create(api, SIMPLE)
    listed = (await api.get("/api/machines")).json()
    assert [m["id"] for m in listed] == [body["id"]]
    assert (await api.get(f"/api/machines/{body['id']}")).status_code == 200


async def test_unknown_machine_is_404(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/machines/m-nope")
    assert response.status_code == 404
    assert response.json()["error"] == "UnknownMachineError"


async def test_collector_route_without_valve_is_rejected(api: httpx.AsyncClient) -> None:
    config = copy.deepcopy(COLLECTOR)
    del config["routes"][0]["valve_entity_id"]
    response = await api.post("/api/machines", json=config)
    assert response.status_code == 422


async def test_reserve_bigger_than_tank_is_rejected(api: httpx.AsyncClient) -> None:
    config = copy.deepcopy(SIMPLE)
    config["tank"]["reserve_ml"] = 5000
    response = await api.post("/api/machines", json=config)
    assert response.status_code == 422


async def test_update_keeps_tank_volume(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await api.put(f"/api/machines/{machine_id}/tank/volume", json={"volume_ml": 1200})

    config = copy.deepcopy(SIMPLE)
    config["name"] = "Фикус на кухне"
    response = await api.put(f"/api/machines/{machine_id}", json=config)

    assert response.status_code == 200
    assert response.json()["config"]["name"] == "Фикус на кухне"
    assert response.json()["status"]["tank"]["volume_ml"] == pytest.approx(1200)


async def test_delete(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    assert (await api.delete(f"/api/machines/{machine_id}")).status_code == 204
    assert (await api.get(f"/api/machines/{machine_id}")).status_code == 404


async def test_machines_survive_restart(gateway: FakeGateway, tmp_path: Path) -> None:
    async with running(
        create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    ) as api:
        machine_id = (await create(api, SIMPLE))["id"]
        await api.put(f"/api/machines/{machine_id}/tank/volume", json={"volume_ml": 900})

    async with running(
        create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    ) as api:
        body = (await api.get(f"/api/machines/{machine_id}")).json()
    assert body["config"]["name"] == "Фикус"
    assert body["status"]["tank"]["volume_ml"] == pytest.approx(900)


# --- Действия ---


async def test_plan(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    gateway.calls.clear()

    response = await api.post(
        f"/api/machines/{machine_id}/plan", json={"route_id": "main", "dose_ml": 100}
    )

    assert response.status_code == 200
    assert response.json()["duration_s"] == pytest.approx(0.1)
    assert gateway.calls == []


async def test_water_runs_pump_and_draws_water(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    gateway.calls.clear()

    response = await api.post(
        f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 100}
    )
    assert response.status_code == 202
    body = await wait_idle(api, machine_id)

    assert gateway.commands() == ["turn_on switch.pump_1", "turn_off switch.pump_1"]
    assert body["status"]["tank"]["volume_ml"] == pytest.approx(2004 - 100, abs=1)
    assert body["status"]["last_watering"]["ok"] is True


async def test_second_watering_while_busy_is_409(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    request = {"route_id": "main", "dose_ml": 100}
    await api.post(f"/api/machines/{machine_id}/water", json=request)
    response = await api.post(f"/api/machines/{machine_id}/water", json=request)
    assert response.status_code == 409
    await wait_idle(api, machine_id)


async def test_dose_over_pump_limit_is_422(api: httpx.AsyncClient) -> None:
    config = copy.deepcopy(SIMPLE)
    config["pump"]["flow"] = {"model": "constant", "flow_ml_s": 1}
    machine_id = (await create(api, config))["id"]
    response = await api.post(
        f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 100}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "PumpRuntimeExceededError"


async def test_not_enough_water_is_409(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    response = await api.post(
        f"/api/machines/{machine_id}/plan", json={"route_id": "main", "dose_ml": 1800}
    )
    assert response.status_code == 409


async def test_emergency_stop_cancels_watering(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    config = copy.deepcopy(SIMPLE)
    config["pump"]["flow"] = {"model": "constant", "flow_ml_s": 10}
    machine_id = (await create(api, config))["id"]
    gateway.calls.clear()
    await api.post(f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 100})
    await asyncio.sleep(0.05)

    response = await api.post(f"/api/machines/{machine_id}/stop")

    assert response.status_code == 200
    body = await wait_idle(api, machine_id)
    assert gateway.commands() == ["turn_on switch.pump_1", "turn_off switch.pump_1"]
    assert body["status"]["pump"]["state"] == "off"
    assert body["status"]["last_watering"]["error"] == "cancelled"
    # Сколько пролилось, неизвестно: бак не списан.
    assert body["status"]["tank"]["volume_ml"] == pytest.approx(2004, abs=1)


async def test_collector_machine_opens_valve_around_pump(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    machine_id = (await create(api, COLLECTOR))["id"]
    assert gateway.commands() == [
        "turn_off switch.pump_1",
        "turn_off input_boolean.valve_1",
        "turn_off input_boolean.valve_2",
    ]
    gateway.calls.clear()

    await api.post(f"/api/machines/{machine_id}/water", json={"route_id": "v2", "dose_ml": 50})
    await wait_idle(api, machine_id)

    assert gateway.commands() == [
        "turn_on input_boolean.valve_2",
        "turn_on switch.pump_1",
        "turn_off switch.pump_1",
        "turn_off input_boolean.valve_2",
    ]


async def test_refill(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await api.put(f"/api/machines/{machine_id}/tank/volume", json={"volume_ml": 800})

    body = (await api.post(f"/api/machines/{machine_id}/tank/refill", json={})).json()

    assert body["status"]["tank"]["volume_ml"] == pytest.approx(2004, abs=1)


async def test_overfill_is_409(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    response = await api.post(f"/api/machines/{machine_id}/tank/refill", json={"volume_ml": 100})
    assert response.status_code == 409


async def test_manual_pump_start_in_ha_is_tracked(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    machine_id = (await create(api, SIMPLE))["id"]

    gateway.emit("switch.pump_1", "on")
    await asyncio.sleep(0.02)

    body = (await api.get(f"/api/machines/{machine_id}")).json()
    assert body["status"]["pump"]["state"] == "on"


async def test_watchdog_stops_pump_left_on(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    config = copy.deepcopy(SIMPLE)
    config["pump"]["max_runtime_s"] = 0.1
    machine_id = (await create(api, config))["id"]
    gateway.emit("switch.pump_1", "on")
    gateway.calls.clear()

    await asyncio.sleep(0.3)

    assert gateway.commands() == ["turn_off switch.pump_1"]
    body = (await api.get(f"/api/machines/{machine_id}")).json()
    assert body["status"]["pump"]["state"] == "off"


async def test_measured_tank(api: httpx.AsyncClient) -> None:
    config = copy.deepcopy(SIMPLE)
    config["tank"] = {
        "geometry": {"shape": "measured", "volume_ml": 1800, "height_mm": 150},
        "reserve_ml": 500,
    }
    body = await create(api, config)
    tank = body["status"]["tank"]
    assert tank["capacity_ml"] == pytest.approx(1800)
    assert tank["usable_ml"] == pytest.approx(1300)


async def test_old_radius_config_is_converted(api: httpx.AsyncClient) -> None:
    config = copy.deepcopy(SIMPLE)
    config["routes"][0]["connection"] = {"length_mm": 700, "inner_radius_mm": 2}
    body = await create(api, config)
    assert body["config"]["routes"][0]["connection"]["inner_diameter_mm"] == 4


# --- Проблемы ---


async def test_problem_appears_when_pump_entity_is_missing(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    config = copy.deepcopy(SIMPLE)
    config["pump"]["entity_id"] = "switch.no_such_pump"
    machine_id = (await create(api, config))["id"]

    problems = (await api.post("/api/problems/check")).json()

    assert [p["kind"] for p in problems] == ["pump_entity_missing"]
    assert problems[0]["machine_id"] == machine_id
    assert problems[0]["blocking"] is True


async def test_problem_closes_when_entity_appears(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    config = copy.deepcopy(SIMPLE)
    config["pump"]["entity_id"] = "switch.no_such_pump"
    await create(api, config)
    await api.post("/api/problems/check")

    gateway.states.append(EntityState("switch.no_such_pump", "off", "Pump"))
    problems = (await api.post("/api/problems/check")).json()

    assert problems == []


async def test_unavailable_entity_is_a_problem(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    await create(api, SIMPLE)
    gateway.states = [EntityState("switch.pump_1", "unavailable", "Pump 1")]

    problems = (await api.post("/api/problems/check")).json()

    assert [p["kind"] for p in problems] == ["pump_entity_missing"]


async def test_no_connection_to_ha_is_a_problem(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    await create(api, SIMPLE)
    gateway.is_connected = False

    problems = (await api.post("/api/problems/check")).json()

    assert [p["kind"] for p in problems] == ["ha_disconnected"]


async def test_low_water_problem_and_refill(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await api.put(f"/api/machines/{machine_id}/tank/volume", json={"volume_ml": 550})

    problems = (await api.post("/api/problems/check")).json()
    assert [p["kind"] for p in problems] == ["tank_low"]
    assert problems[0]["blocking"] is False

    await api.post(f"/api/machines/{machine_id}/tank/refill", json={})
    assert (await api.post("/api/problems/check")).json() == []


async def test_acknowledge_and_mute(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    await create(api, SIMPLE)
    gateway.is_connected = False
    problem = (await api.post("/api/problems/check")).json()[0]

    acked = (await api.post(f"/api/problems/{problem['id']}/ack")).json()
    assert acked["acknowledged"] is True

    muted = (await api.post(f"/api/problems/{problem['id']}/mute", json={"hours": 2})).json()
    assert muted["muted_until"] is not None

    unmuted = (await api.post(f"/api/problems/{problem['id']}/unmute")).json()
    assert unmuted["muted_until"] is None

    listed = (await api.get("/api/problems")).json()
    assert len(listed) == 1


async def test_unknown_problem_is_404(api: httpx.AsyncClient) -> None:
    assert (await api.post("/api/problems/m-1|tank_low|/ack")).status_code == 404
    assert (await api.post("/api/problems/garbage/ack")).status_code == 404


# --- Проблемы мешают поливу ---


async def test_unavailable_pump_blocks_watering(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await api.post(f"/api/machines/{machine_id}/tank/refill", json={})
    gateway.calls.clear()
    # Насос пропал только что: круг проверки ещё не прошёл, но полив всё равно запрещён.
    gateway.states[0] = EntityState("switch.pump_1", "unavailable", "Pump 1")

    response = await api.post(
        f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 50}
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "WateringBlockedError"
    assert [p["kind"] for p in body["problems"]] == ["pump_entity_missing"]
    assert gateway.commands() == []
    status = (await api.get(f"/api/machines/{machine_id}")).json()["status"]
    assert [b["kind"] for b in status["blockers"]] == ["pump_entity_missing"]


async def test_queue_submit_is_blocked_too(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await api.post(f"/api/machines/{machine_id}/tank/refill", json={})
    gateway.is_connected = False

    response = await api.post(
        "/api/queue", json={"machine_id": machine_id, "route_id": "main", "dose_ml": 50}
    )

    assert response.status_code == 409
    assert (await api.get("/api/queue")).json()["queued"] == []


async def test_empty_tank_blocks_watering(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await api.put(f"/api/machines/{machine_id}/tank/volume", json={"volume_ml": 0})

    response = await api.post(
        f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 50}
    )

    assert response.status_code == 409
    assert [p["kind"] for p in response.json()["problems"]] == ["tank_empty"]


async def test_missing_valve_blocks_only_its_plant(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    machine_id = (await create(api, COLLECTOR))["id"]
    await api.post(f"/api/machines/{machine_id}/tank/refill", json={})
    gateway.states = [s for s in gateway.states if s.entity_id != "input_boolean.valve_1"]

    blocked = await api.post(
        f"/api/machines/{machine_id}/water", json={"route_id": "v1", "dose_ml": 50}
    )
    allowed = await api.post(
        f"/api/machines/{machine_id}/water", json={"route_id": "v2", "dose_ml": 50}
    )

    assert blocked.status_code == 409
    assert allowed.status_code == 202
    await wait_idle(api, machine_id)


async def test_problem_appearing_while_queued_fails_the_request(tmp_path: Path) -> None:
    gateway = FakeGateway()
    app = create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    async with running(app) as api:
        machine_id = (await create(api, SIMPLE))["id"]
        await api.post(f"/api/machines/{machine_id}/tank/refill", json={})
        # Заявка в очереди, а насос тем временем пропал.
        gateway.states[0] = EntityState("switch.pump_1", "unavailable", "Pump 1")
        gateway.calls.clear()
        request = app.state.controller.queue.submit(machine_id, "main", 50)

        for _ in range(200):
            if request.is_finished:
                break
            await asyncio.sleep(0.01)

        assert request.state.value == "failed"
        assert "WateringBlockedError" in (request.error or "")
        assert gateway.commands() == []
        titles = [sent["title"] for sent in gateway.notifications]
        assert "Полив не удался" in titles
