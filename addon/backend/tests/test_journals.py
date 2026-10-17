"""Журналы: очистка поливов, калибровок и проблем, срок хранения."""

import asyncio
import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from plant_control.application.queue import RequestSource, RequestState, WateringRequest

from plant_control_addon.api.app import create_app
from plant_control_addon.ha.client import EntityState
from plant_control_addon.storage import MachineStore
from tests.conftest import FakeGateway, running, settings
from tests.test_machines_api import SIMPLE, create, wait_idle


def state(api: httpx.AsyncClient) -> Any:
    return api._transport.app.state  # type: ignore[attr-defined]


async def water(api: httpx.AsyncClient, machine_id: str, dose: float = 10) -> None:
    response = await api.post(
        f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": dose}
    )
    assert response.status_code == 202
    await wait_idle(api, machine_id)


async def history(api: httpx.AsyncClient) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = (await api.get("/api/queue")).json()["history"]
    return result


# --- Поливы ---


async def test_clear_all_waterings(api: httpx.AsyncClient, tmp_path: Path) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await water(api, machine_id)
    await water(api, machine_id)
    assert len(await history(api)) == 2

    response = await api.post("/api/journals/waterings/clear", json={})

    assert response.json() == {"deleted": 2}
    assert await history(api) == []
    store: MachineStore = state(api).journals._store
    assert await store.load_waterings(100) == []


async def test_clear_one_watering(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await water(api, machine_id)
    await water(api, machine_id)
    first, second = await history(api)

    await api.post("/api/journals/waterings/clear", json={"ids": [first["id"]]})

    assert [item["id"] for item in await history(api)] == [second["id"]]


async def test_clear_only_failed_waterings(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await water(api, machine_id)
    journals = state(api).journals
    now = datetime.now(UTC)
    failed = WateringRequest(
        id="failed-1",
        seq=99,
        machine_id=machine_id,
        route_id="main",
        dose_ml=5,
        source=RequestSource.SCHEDULE,
        requested_at=now,
        state=RequestState.FAILED,
        finished_at=now,
        error="boom",
    )
    journals._queue._history.insert(0, failed)
    await journals._store.save_watering(failed)

    deleted = (await api.post("/api/journals/waterings/clear", json={"scope": "problems"})).json()

    assert deleted == {"deleted": 1}
    assert [item["state"] for item in await history(api)] == ["done"]
    assert [r.id for r in await journals._store.load_waterings(10)] != ["failed-1"]


async def test_clear_waterings_older_than(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await water(api, machine_id)

    response = await api.post("/api/journals/waterings/clear", json={"older_than_days": 7})

    assert response.json() == {"deleted": 0}
    assert len(await history(api)) == 1


# --- Калибровки ---


async def test_clear_calibrations_keeps_the_active_one(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    store: MachineStore = state(api).journals._store
    old = await store.save_calibration(machine_id, "main", "marks", "{}")
    active = await store.save_calibration(machine_id, "main", "marks", "{}")
    registry = state(api).registry
    config = registry.entry(machine_id).config.model_copy(deep=True)
    config.routes[0].calibration = config.routes[0].calibration or _calibration()
    config.routes[0].calibration.record_id = active
    await registry.update(machine_id, config)

    response = await api.post("/api/journals/calibrations/clear", json={"machine_id": machine_id})

    assert response.json() == {"deleted": 1}
    left = (await api.get(f"/api/machines/{machine_id}/calibrations")).json()
    assert [row["id"] for row in left] == [active]
    assert old != active


async def test_clear_one_calibration(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    store: MachineStore = state(api).journals._store
    first = await store.save_calibration(machine_id, "main", "marks", "{}")
    second = await store.save_calibration(machine_id, "main", "time", "{}")

    await api.post(
        "/api/journals/calibrations/clear", json={"machine_id": machine_id, "ids": [first]}
    )

    left = (await api.get(f"/api/machines/{machine_id}/calibrations")).json()
    assert [row["id"] for row in left] == [second]


async def test_clear_calibrations_of_unknown_machine_is_404(api: httpx.AsyncClient) -> None:
    response = await api.post("/api/journals/calibrations/clear", json={"machine_id": "nope"})
    assert response.status_code == 404


def _calibration() -> Any:
    from plant_control_addon.config import RouteCalibrationConfig

    return RouteCalibrationConfig.model_validate(
        {"flow_points": [{"tank_volume_ml": 1000.0, "flow_ml_s": 5.0}], "prime_s": 1.0}
    )


# --- Проблемы ---


async def test_problem_journal_records_open_and_close(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    config = copy.deepcopy(SIMPLE)
    config["pump"]["entity_id"] = "switch.no_such_pump"
    machine_id = (await create(api, config))["id"]
    await api.post("/api/problems/check")
    await asyncio.sleep(0.05)

    log = (await api.get("/api/journals/problems")).json()
    assert [(r["kind"], r["closed_at"]) for r in log] == [("pump_entity_missing", None)]
    assert log[0]["machine_name"] == config["name"]
    assert log[0]["machine_id"] == machine_id

    gateway.states.append(EntityState("switch.no_such_pump", "off", "Pump"))
    await api.post("/api/problems/check")
    await asyncio.sleep(0.05)

    log = (await api.get("/api/journals/problems")).json()
    assert log[0]["closed_at"] is not None


async def test_clear_problem_journal_keeps_open_problems(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    config = copy.deepcopy(SIMPLE)
    config["pump"]["entity_id"] = "switch.no_such_pump"
    await create(api, config)
    await api.post("/api/problems/check")
    gateway.states.append(EntityState("switch.no_such_pump", "off", "Pump"))
    await api.post("/api/problems/check")
    gateway.states = [s for s in gateway.states if s.entity_id != "switch.no_such_pump"]
    await api.post("/api/problems/check")
    await asyncio.sleep(0.05)
    assert len((await api.get("/api/journals/problems")).json()) == 2

    response = await api.post("/api/journals/problems/clear", json={})

    assert response.json() == {"deleted": 1}
    log = (await api.get("/api/journals/problems")).json()
    assert [r["closed_at"] for r in log] == [None]


async def test_open_problems_are_closed_on_restart(gateway: FakeGateway, tmp_path: Path) -> None:
    config = copy.deepcopy(SIMPLE)
    config["pump"]["entity_id"] = "switch.no_such_pump"
    app = create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    async with running(app) as api:
        await create(api, config)
        await api.post("/api/problems/check")
        await asyncio.sleep(0.05)

    gateway.states.append(EntityState("switch.no_such_pump", "off", "Pump"))
    app = create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    async with running(app) as api:
        log = (await api.get("/api/journals/problems")).json()

    assert len(log) == 1
    assert log[0]["closed_at"] is not None


# --- Срок хранения ---


async def test_keep_days_setting_prunes_old_records(api: httpx.AsyncClient) -> None:
    machine_id = (await create(api, SIMPLE))["id"]
    await water(api, machine_id)
    journals = state(api).journals
    # Запись "из прошлого": поливу 40 дней.
    old = journals._queue.history()[0]
    old.finished_at = datetime.now(UTC) - timedelta(days=40)
    await journals._store.save_watering(old)
    await water(api, machine_id)

    assert (await api.get("/api/journals/settings")).json() == {"keep_days": None}
    response = await api.put("/api/journals/settings", json={"keep_days": 30})

    assert response.status_code == 200
    assert (await api.get("/api/journals/settings")).json() == {"keep_days": 30}
    assert len(await history(api)) == 1


async def test_keep_days_must_be_positive(api: httpx.AsyncClient) -> None:
    response = await api.put("/api/journals/settings", json={"keep_days": 0})
    assert response.status_code == 422
