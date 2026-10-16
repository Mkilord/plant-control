"""Тесты мастера калибровки, журнала калибровок и автоподстройки."""

import asyncio
import copy
from pathlib import Path
from typing import Any

import httpx
import pytest

from plant_control_addon.api.app import create_app
from tests.conftest import FakeGateway, legacy, running, settings
from tests.test_machines_api import COLLECTOR, wait_idle

# Машина без паспорта насоса: поливает только по калибровке.
CALIBRATED: dict[str, Any] = {
    "name": "Новая",
    "tank": {
        "geometry": {"shape": "measured", "volume_ml": 10000, "height_mm": 200},
        "reserve_ml": 0,
    },
    "pump": {"entity_id": "switch.pump_1", "max_runtime_s": 60, "cooldown_s": 0},
    "plumbing": {"type": "direct"},
    "flow_mode": "calibrated",
    "routes": [{"id": "main", "connection": {"length_mm": 700, "inner_diameter_mm": 4}}],
}


async def create(api: httpx.AsyncClient, config: dict[str, Any]) -> str:
    response = await api.post("/api/machines", json=await legacy(api, config))
    assert response.status_code == 201, response.text
    machine_id: str = response.json()["id"]
    return machine_id


async def open_session(
    api: httpx.AsyncClient, machine_id: str, route_id: str = "main", **body: Any
) -> dict[str, Any]:
    payload = {"route_id": route_id, "method": "marks", "marks_ml": [500, 1000, 1500], **body}
    response = await api.post(f"/api/machines/{machine_id}/calibration", json=payload)
    assert response.status_code == 201, response.text
    session: dict[str, Any] = response.json()
    return session


async def post(api: httpx.AsyncClient, url: str, body: Any = None) -> dict[str, Any]:
    response = await api.post(url, json=body)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


async def marks_run(
    api: httpx.AsyncClient, sid: str, marks: list[tuple[float, float]], final: float
) -> dict[str, Any]:
    base = f"/api/calibration/sessions/{sid}"
    await post(api, f"{base}/start")
    for t, v in marks:
        session = await post(api, f"{base}/mark", {"t_s": t, "volume_ml": v})
    assert session["state"] == "awaiting_volume"
    return await post(api, f"{base}/volume", {"volume_ml": final})


async def test_new_machine_without_calibration_cannot_water(api: httpx.AsyncClient) -> None:
    machine_id = await create(api, CALIBRATED)
    body = (await api.get(f"/api/machines/{machine_id}")).json()
    assert body["status"]["flows"] == [
        {
            "route_id": "main",
            "source": "none",
            "inherited_from": None,
            "flow_points": [],
            "prime_s": None,
            "afterflow_ml": None,
            "calibrated_at": None,
            "due": False,
            "stale": False,
            "copied_from": None,
        }
    ]
    response = await api.post(
        f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 100}
    )
    assert response.status_code == 409
    assert response.json()["error"] == "RouteNotCalibratedError"


async def test_advanced_mode_needs_pump_flow(api: httpx.AsyncClient) -> None:
    config = copy.deepcopy(CALIBRATED)
    config["flow_mode"] = "advanced"
    response = await api.post("/api/machines", json=await legacy(api, config))
    assert response.status_code == 422


async def test_marks_calibration_end_to_end(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    machine_id = await create(api, CALIBRATED)
    session = await open_session(api, machine_id)
    sid = session["id"]
    assert session["state"] == "ready"

    # Пока идёт калибровка, машина занята.
    machine = (await api.get(f"/api/machines/{machine_id}")).json()
    assert machine["status"]["busy"]
    assert machine["status"]["calibration_session"] == sid

    gateway.calls.clear()
    session = await marks_run(api, sid, [(53, 500), (103, 1000), (153, 1500)], 1530)
    # Насос включился и выключился на последней метке.
    assert gateway.commands() == ["turn_on switch.pump_1", "turn_off switch.pump_1"]
    assert session["state"] == "ready"
    assert session["runs"][0]["stop_reason"] == "last_mark"
    result = session["result"]
    assert result["flow_ml_s"] == pytest.approx(10)
    assert result["prime_s"] == pytest.approx(3)
    assert result["afterflow_ml"] == pytest.approx(30)

    saved = await post(api, f"/api/calibration/sessions/{sid}/save", {})
    assert not saved["status"]["busy"]
    route = saved["config"]["routes"][0]
    assert route["calibration"]["flow_points"][0]["flow_ml_s"] == pytest.approx(10)
    assert saved["config"]["base_route"] == "main"
    # Вода, налитая в ёмкость, ушла из бака.
    assert saved["status"]["tank"]["volume_ml"] == pytest.approx(10000 - 1530)
    assert saved["status"]["flows"][0]["source"] == "own"

    plan = await post(api, f"/api/machines/{machine_id}/plan", {"route_id": "main", "dose_ml": 530})
    assert plan["duration_s"] == pytest.approx(53)

    history = (await api.get(f"/api/machines/{machine_id}/calibrations")).json()
    assert len(history) == 1
    assert history[0]["data"]["runs"][0]["marks"] == [[53, 500], [103, 1000], [153, 1500]]


async def test_marks_must_follow_targets(api: httpx.AsyncClient) -> None:
    machine_id = await create(api, CALIBRATED)
    sid = (await open_session(api, machine_id))["id"]
    base = f"/api/calibration/sessions/{sid}"
    await post(api, f"{base}/start")
    response = await api.post(f"{base}/mark", json={"t_s": 10, "volume_ml": 1000})
    assert response.status_code == 409
    await post(api, f"{base}/mark", {"t_s": 3, "volume_ml": 0})
    await post(api, f"{base}/mark", {"t_s": 10, "volume_ml": 500})
    response = await api.post(f"{base}/mark", json={"t_s": 9, "volume_ml": 1000})
    assert response.status_code == 422
    await api.delete(base)


async def test_user_stop_aborts_run(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    machine_id = await create(api, CALIBRATED)
    sid = (await open_session(api, machine_id))["id"]
    base = f"/api/calibration/sessions/{sid}"
    await post(api, f"{base}/start")
    session = await post(api, f"{base}/stop")
    assert session["state"] == "awaiting_volume"
    assert session["runs"][0]["stop_reason"] == "user"
    assert gateway.commands()[-1] == "turn_off switch.pump_1"
    # Объём прерванного прогона можно не мерить.
    session = await post(api, f"{base}/skip-volume")
    assert session["state"] == "ready"
    assert session["result"] is None


async def test_close_session_stops_pump_and_frees_machine(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    machine_id = await create(api, CALIBRATED)
    sid = (await open_session(api, machine_id))["id"]
    await post(api, f"/api/calibration/sessions/{sid}/start")
    assert (await api.delete(f"/api/calibration/sessions/{sid}")).status_code == 204
    assert gateway.commands()[-1] == "turn_off switch.pump_1"
    machine = (await api.get(f"/api/machines/{machine_id}")).json()
    assert not machine["status"]["busy"]
    assert machine["status"]["pump"]["state"] == "off"


async def test_emergency_stop_closes_calibration(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    machine_id = await create(api, CALIBRATED)
    sid = (await open_session(api, machine_id))["id"]
    await post(api, f"/api/calibration/sessions/{sid}/start")
    await post(api, f"/api/machines/{machine_id}/stop")
    assert (await api.get(f"/api/calibration/sessions/{sid}")).status_code == 404
    assert gateway.commands()[-1] == "turn_off switch.pump_1"


async def test_lost_heartbeat_stops_pump(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    response = await api.put(
        "/api/calibration/settings", json={"heartbeat_timeout_s": 0.3, "idle_timeout_s": 60}
    )
    assert response.status_code == 200
    machine_id = await create(api, CALIBRATED)
    sid = (await open_session(api, machine_id))["id"]
    await post(api, f"/api/calibration/sessions/{sid}/start")
    for _ in range(50):
        session = (await api.get(f"/api/calibration/sessions/{sid}")).json()
        if session["state"] != "running":
            break
        await asyncio.sleep(0.1)
    assert session["runs"][0]["stop_reason"] == "heartbeat"
    assert gateway.commands()[-1] == "turn_off switch.pump_1"


async def test_timed_calibration(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    machine_id = await create(api, CALIBRATED)
    session = await open_session(api, machine_id, method="timed", marks_ml=[])
    base = f"/api/calibration/sessions/{session['id']}"

    for duration, volume in [(0.2, 80), (0.4, 180)]:
        await post(api, f"{base}/run", {"duration_s": duration})
        for _ in range(50):
            state = (await api.get(base)).json()["state"]
            if state == "awaiting_volume":
                break
            await asyncio.sleep(0.05)
        assert state == "awaiting_volume"
        session = await post(api, f"{base}/volume", {"volume_ml": volume})

    assert session["result"]["flow_ml_s"] == pytest.approx(500)
    assert session["result"]["prime_s"] == pytest.approx(0.04)
    assert "too_fast" in session["result"]["warnings"]
    # Длиннее предела насоса нельзя.
    response = await api.post(f"{base}/run", json={"duration_s": 61})
    assert response.status_code == 422


async def test_watering_waits_while_calibrating(api: httpx.AsyncClient) -> None:
    machine_id = await create(api, CALIBRATED)
    sid = (await open_session(api, machine_id))["id"]
    await marks_run(api, sid, [(53, 500), (103, 1000), (153, 1500)], 1530)
    await post(api, f"/api/calibration/sessions/{sid}/save", {})

    sid = (await open_session(api, machine_id))["id"]
    response = await api.post(
        f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 100}
    )
    assert response.status_code == 409
    response = await api.put(f"/api/machines/{machine_id}", json=await legacy(api, CALIBRATED))
    assert response.status_code == 409
    await api.delete(f"/api/calibration/sessions/{sid}")


async def test_collector_routes_inherit_base_flow(api: httpx.AsyncClient) -> None:
    config = copy.deepcopy(COLLECTOR)
    del config["pump"]["flow"]
    config["flow_mode"] = "calibrated"
    # Вторая трубка длиннее первой: 4 мм внутри, на 1000 мм больше - ещё 12.6 мл.
    config["routes"][1]["connection"]["length_mm"] = 1300
    machine_id = await create(api, config)

    sid = (await open_session(api, machine_id, route_id="v1"))["id"]
    await marks_run(api, sid, [(53, 500), (103, 1000), (153, 1500)], 1530)
    saved = await post(api, f"/api/calibration/sessions/{sid}/save", {})

    flows = {f["route_id"]: f for f in saved["status"]["flows"]}
    assert flows["v1"]["source"] == "own"
    assert flows["v2"]["source"] == "inherited"
    assert flows["v2"]["inherited_from"] == "v1"
    extra = 3.14159 * 2**2 * 1000 / 1000
    # Первый прогон шёл с пустой трубкой до коллектора (6.28 мл): её в задержке нет.
    supply = 3.14159 * 2**2 * 500 / 1000
    assert flows["v1"]["prime_s"] == pytest.approx(3 - supply / 10, abs=0.01)
    assert flows["v2"]["prime_s"] == pytest.approx(3 - supply / 10 + extra / 10, abs=0.01)
    assert flows["v2"]["afterflow_ml"] == pytest.approx(30 + extra, abs=0.1)


async def test_calibration_with_empty_supply_excludes_supply_from_prime(
    api: httpx.AsyncClient,
) -> None:
    config = copy.deepcopy(COLLECTOR)
    config["flow_mode"] = "calibrated"
    machine_id = await create(api, config)
    sid = (await open_session(api, machine_id, route_id="v1"))["id"]
    session = await marks_run(api, sid, [(53, 500), (103, 1000), (153, 1500)], 1530)
    # Трубка до коллектора 500 мм x 4 мм: 6.28 мл, при 10 мл/с это 0.63 с.
    assert session["result"]["prime_s"] == pytest.approx(3 - 0.628, abs=0.01)


async def test_second_level(api: httpx.AsyncClient) -> None:
    machine_id = await create(api, CALIBRATED)
    sid = (await open_session(api, machine_id))["id"]
    await marks_run(api, sid, [(53, 500), (103, 1000), (153, 1500)], 1530)
    await post(api, f"/api/calibration/sessions/{sid}/save", {})

    # Почти пустой бак: расход 8 мл/с.
    await api.put(f"/api/machines/{machine_id}/tank/volume", json={"volume_ml": 2000})
    sid = (await open_session(api, machine_id))["id"]
    session = await marks_run(api, sid, [(65, 500), (127.5, 1000), (190, 1500)], 1520)
    assert session["second_level_possible"]
    saved = await post(api, f"/api/calibration/sessions/{sid}/save", {"mode": "second_level"})
    points = saved["config"]["routes"][0]["calibration"]["flow_points"]
    assert len(points) == 2
    assert points[1]["flow_ml_s"] == pytest.approx(8)


async def test_flow_suggestion(api: httpx.AsyncClient) -> None:
    config = copy.deepcopy(CALIBRATED)
    # Быстрый насос, чтобы поливы в тесте шли доли секунды.
    config["routes"][0]["calibration"] = {
        "flow_points": [{"tank_volume_ml": 5000, "flow_ml_s": 1000}]
    }
    machine_id = await create(api, config)
    await api.put(f"/api/machines/{machine_id}/tank/volume", json={"volume_ml": 8000})

    for _ in range(3):
        response = await api.post(
            f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 50}
        )
        assert response.status_code == 202, response.text
        await wait_idle(api, machine_id)

    # По расчёту ушло 150 мл, на деле 200.
    body = (
        await api.put(f"/api/machines/{machine_id}/tank/volume", json={"volume_ml": 7800})
    ).json()
    suggestion = body["status"]["flow_suggestion"]
    assert suggestion["factor"] == pytest.approx(200 / 150)

    applied = await post(api, f"/api/machines/{machine_id}/flow-suggestion", {"apply": True})
    assert applied["status"]["flow_suggestion"] is None
    flow = applied["config"]["routes"][0]["calibration"]["flow_points"][0]["flow_ml_s"]
    assert flow == pytest.approx(1000 * 200 / 150)


async def test_reminder_marks_old_calibration_due(api: httpx.AsyncClient) -> None:
    config = copy.deepcopy(CALIBRATED)
    config["routes"][0]["calibration"] = {
        "flow_points": [{"tank_volume_ml": 5000, "flow_ml_s": 10}],
        "calibrated_at": "2020-01-01T00:00:00Z",
    }
    machine_id = await create(api, config)
    body = (await api.get(f"/api/machines/{machine_id}")).json()
    assert body["status"]["flows"][0]["due"] is False
    await api.put("/api/calibration/settings", json={"reminder_weeks": 4})
    body = (await api.get(f"/api/machines/{machine_id}")).json()
    assert body["status"]["flows"][0]["due"] is True


async def test_settings_and_suggestion_survive_restart(
    gateway: FakeGateway, tmp_path: Path
) -> None:
    async with running(
        create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    ) as api:
        await api.put("/api/calibration/settings", json={"tune_deviation_pct": 25})
    async with running(
        create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    ) as api:
        body = (await api.get("/api/calibration/settings")).json()
        assert body["tune_deviation_pct"] == 25
