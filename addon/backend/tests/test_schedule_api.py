"""Тесты расписаний, очереди и групп питания через API."""

import asyncio
import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from plant_control_addon.api.app import create_app
from tests.conftest import FakeGateway, running, settings
from tests.test_machines_api import COLLECTOR, SIMPLE, create, wait_idle

EVERY_DAY = {
    "enabled": True,
    "rule": {"type": "weekly", "days": [0, 1, 2, 3, 4, 5, 6], "times": ["08:00", "20:00"]},
    "dose_ml": 150,
}


def with_group(name: str, limit: int, plant: str) -> dict[str, Any]:
    config = copy.deepcopy(SIMPLE)
    config["name"] = plant
    config["power_group"] = name
    config["power_limit"] = limit
    config["power_gap_s"] = 0
    return config


# --- Расписание ---


async def test_schedule_is_saved_and_shows_next_run(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]

    response = await api.put(f"/api/machines/{machine_id}/routes/main/schedule", json=EVERY_DAY)

    assert response.status_code == 200
    schedules = response.json()["status"]["schedules"]
    assert len(schedules) == 1
    assert schedules[0]["dose_ml"] == 150
    assert schedules[0]["next_run_at"] is not None
    assert response.json()["config"]["routes"][0]["schedule"]["rule"]["type"] == "weekly"


async def test_schedule_list_and_removal(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await api.put(f"/api/machines/{machine_id}/routes/main/schedule", json=EVERY_DAY)

    listed = (await api.get("/api/schedules")).json()
    assert [item["route_id"] for item in listed] == ["main"]
    assert listed[0]["machine_name"] == "Фикус"

    await api.delete(f"/api/machines/{machine_id}/routes/main/schedule")
    assert (await api.get("/api/schedules")).json() == []


async def test_schedule_for_unknown_route_is_404(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    response = await api.put(f"/api/machines/{machine_id}/routes/nope/schedule", json=EVERY_DAY)
    assert response.status_code == 404
    assert response.json()["error"] == "UnknownRouteError"


async def test_interval_schedule_survives_restart(gateway: FakeGateway, tmp_path: Path) -> None:
    rule = {
        "enabled": True,
        "rule": {
            "type": "interval",
            "every_days": 3,
            "times": ["09:30"],
            "start_date": "2026-09-01",
        },
    }
    async with running(
        create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    ) as api:
        machine_id = (await create(api, SIMPLE))["id"]
        await api.put(f"/api/machines/{machine_id}/routes/main/schedule", json=rule)

    async with running(
        create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    ) as api:
        listed = (await api.get("/api/schedules")).json()
        assert len(listed) == 1
        # Дозы в расписании нет - берётся доза маршрута.
        assert listed[0]["dose_ml"] == 100
        assert "09:30:00" in listed[0]["next_run_at"]


async def test_schedule_check_waters_when_the_time_has_come(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await api.post(f"/api/machines/{machine_id}/tank/refill", json={})
    now = datetime.now(UTC)
    # Срок - минуту назад, чтобы проверка сработала прямо сейчас.
    rule = {
        "enabled": True,
        "rule": {
            "type": "weekly",
            "days": [0, 1, 2, 3, 4, 5, 6],
            "times": [(now - timedelta(minutes=1)).strftime("%H:%M")],
        },
        "dose_ml": 60,
    }
    await api.put(f"/api/machines/{machine_id}/routes/main/schedule", json=rule)

    response = await api.post("/api/schedules/check")

    assert response.status_code == 200
    assert [item["source"] for item in response.json()["submitted"]] == ["schedule"]
    body = await wait_idle(api, machine_id)
    assert body["status"]["last_watering"]["dose_ml"] == 60
    # Повторная проверка того же срока ничего не добавляет.
    assert (await api.post("/api/schedules/check")).json()["submitted"] == []


# --- Очередь ---


async def test_queue_shows_request_and_history(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await api.post(f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": 50})
    await wait_idle(api, machine_id)

    queue = (await api.get("/api/queue")).json()
    assert queue["queued"] == []
    assert [item["state"] for item in queue["history"]] == ["done"]
    assert queue["history"][0]["source"] == "manual"


async def test_queued_request_can_be_cancelled(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    body = {"machine_id": machine_id, "route_id": "main", "dose_ml": 50, "max_wait_min": 10}
    # Первая заявка занимает машину, вторая ждёт своей очереди - её и отменяем.
    await api.post("/api/queue", json=body)
    waiting = (await api.post("/api/queue", json=body)).json()

    response = await api.delete(f"/api/queue/{waiting['id']}")

    assert response.status_code == 200
    assert response.json()["state"] == "cancelled"
    await wait_idle(api, machine_id)
    states = {item["id"]: item["state"] for item in (await api.get("/api/queue")).json()["history"]}
    assert states[waiting["id"]] == "cancelled"


async def test_unknown_request_is_404(api: httpx.AsyncClient) -> None:
    response = await api.delete("/api/queue/nope")
    assert response.status_code == 404
    assert response.json()["error"] == "UnknownRequestError"


# --- Группы питания ---


async def test_one_power_group_waters_one_by_one(gateway: FakeGateway, tmp_path: Path) -> None:
    # Два насоса от одного блока питания: второй должен ждать первого.
    app = create_app(
        ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False, queue_tick=0.02
    )
    async with running(app) as api:
        slow = with_group("usb", 1, "Фикус")
        slow["pump"]["flow"] = {"model": "constant", "flow_ml_s": 200}
        first = (await create(api, slow))["id"]
        second_config = with_group("usb", 1, "Монстера")
        second_config["pump"]["entity_id"] = "switch.pump_2"
        second = (await create(api, second_config))["id"]

        await api.post(f"/api/machines/{first}/water", json={"route_id": "main", "dose_ml": 100})
        await api.post("/api/queue", json={"machine_id": second, "route_id": "main", "dose_ml": 50})
        await asyncio.sleep(0.1)

        queue = (await api.get("/api/queue")).json()
        assert [item["machine_id"] for item in queue["running"]] == [first]
        assert [item["machine_id"] for item in queue["queued"]] == [second]

        await wait_idle(api, first)
        await wait_idle(api, second)
        history = (await api.get("/api/queue")).json()["history"]
        assert {item["state"] for item in history} == {"done"}


async def test_machines_without_a_group_water_at_the_same_time(
    gateway: FakeGateway, tmp_path: Path
) -> None:
    app = create_app(
        ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False, queue_tick=0.02
    )
    async with running(app) as api:
        slow = copy.deepcopy(COLLECTOR)
        slow["pump"]["flow"] = {"model": "constant", "flow_ml_s": 200}
        first = (await create(api, slow))["id"]
        other = copy.deepcopy(slow)
        other["name"] = "Монстера"
        other["pump"]["entity_id"] = "switch.pump_2"
        second = (await create(api, other))["id"]

        await api.post(f"/api/machines/{first}/water", json={"route_id": "v1", "dose_ml": 100})
        await api.post(f"/api/machines/{second}/water", json={"route_id": "v1", "dose_ml": 100})
        await asyncio.sleep(0.1)

        running_ids = {
            item["machine_id"] for item in (await api.get("/api/queue")).json()["running"]
        }
        assert running_ids == {first, second}

        await wait_idle(api, first)
        await wait_idle(api, second)


async def test_busy_machine_rejects_a_second_manual_watering(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    request = {"route_id": "main", "dose_ml": 100}
    first = await api.post(f"/api/machines/{machine_id}/water", json=request)
    second = await api.post(f"/api/machines/{machine_id}/water", json=request)

    assert first.status_code == 202
    assert first.json()["request"]["state"] == "queued"
    assert second.status_code == 409
    await wait_idle(api, machine_id)


# --- Часовой пояс ---


def test_unknown_timezone_falls_back_to_utc() -> None:
    """Без базы часовых поясов (так бывает в Windows) add-on не должен падать."""
    assert settings(timezone="Europe/Moscow").checked_timezone in ("Europe/Moscow", "UTC")
    assert settings(timezone="Nowhere/Nothing").checked_timezone == "UTC"
    assert settings(timezone="Nowhere/Nothing").notification_rules.timezone == "UTC"


async def test_schedule_works_with_a_broken_timezone(gateway: FakeGateway, tmp_path: Path) -> None:
    app = create_app(
        ha=gateway, settings=settings(timezone="Nowhere/Nothing"), data_dir=tmp_path, mqtt=False
    )
    async with running(app) as api:
        machine_id = (await create(api, SIMPLE))["id"]
        response = await api.put(f"/api/machines/{machine_id}/routes/main/schedule", json=EVERY_DAY)

        assert response.status_code == 200
        assert response.json()["status"]["schedules"][0]["next_run_at"] is not None
