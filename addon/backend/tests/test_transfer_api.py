"""Тесты экспорта и импорта машин."""

from pathlib import Path
from typing import Any

import httpx

from plant_control_addon.api.app import create_app
from tests.conftest import FakeGateway, running, settings
from tests.test_catalog_api import PUMP, TANK, add, machine


async def two_systems(gateway: FakeGateway, tmp_path: Path) -> tuple[Any, Any]:
    first = create_app(ha=gateway, settings=settings(), data_dir=tmp_path / "a", mqtt=False)
    second = create_app(ha=gateway, settings=settings(), data_dir=tmp_path / "b", mqtt=False)
    return first, second


async def test_export_carries_machines_with_their_equipment(
    gateway: FakeGateway, tmp_path: Path
) -> None:
    first, second = await two_systems(gateway, tmp_path)
    async with running(first) as api:
        tank = await add(api, "tank", TANK)
        pump = await add(api, "pump", PUMP)
        await add(api, "tank", {**TANK, "name": "Лишний бак"})
        schedule = await add(
            api,
            "schedule",
            {"name": "Утро", "rule": {"type": "weekly", "days": [0], "times": ["08:00"]}},
        )
        created = await machine(api, tank, pump)
        await api.put(
            f"/api/machines/{created['id']}/routes/main/schedule-link", json={"template": schedule}
        )
        bundle = (await api.get("/api/export")).json()

    assert bundle["format"] == "plant-control-machines"
    # В файл попадает только то, на что ссылаются машины.
    assert list(bundle["catalog"]["tank"]) == [tank]
    assert list(bundle["catalog"]["schedule"]) == [schedule]

    async with running(second) as api:
        # Такой же насос уже есть: его переиспользуют, а не создают второй.
        await add(api, "pump", PUMP)
        plan = (await api.post("/api/import/preview", json=bundle)).json()
        assert plan["new_items"] == 2  # бак и расписание
        assert plan["reused_items"] == 1
        assert plan["machines"][0]["taken"] == {}

        response = await api.post("/api/import", json={"bundle": bundle})
        assert response.status_code == 201, response.text
        imported = response.json()[0]
        assert imported["config"]["name"] == "Поливалка"
        assert imported["config"]["tank_type"] != tank
        flow = imported["status"]["flows"][0]
        # Калибровка переехала и действует: перекалибровка не нужна.
        assert flow["source"] == "own" and not flow["stale"]
        assert imported["status"]["schedules"][0]["template"] is not None
        catalog = (await api.get("/api/catalog")).json()
        assert len(catalog["pump"]) == 1


async def test_stale_calibration_stays_stale(gateway: FakeGateway, tmp_path: Path) -> None:
    first, second = await two_systems(gateway, tmp_path)
    async with running(first) as api:
        tank = await add(api, "tank", TANK)
        pump = await add(api, "pump", PUMP)
        created = await machine(api, tank, pump)
        config = created["config"]
        config["routes"][0]["connection"]["length_mm"] = 1500
        await api.put(f"/api/machines/{created['id']}", json=config)
        bundle = (await api.get("/api/export")).json()

    async with running(second) as api:
        imported = (await api.post("/api/import", json={"bundle": bundle})).json()[0]
        assert imported["status"]["flows"][0]["stale"]


async def test_machine_with_taken_relay_is_not_imported(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    created = await machine(api, tank, pump)
    bundle = (await api.get(f"/api/export?machines={created['id']}")).json()

    plan = (await api.post("/api/import/preview", json=bundle)).json()
    assert plan["machines"][0]["taken"] == {"switch.pump_1": "Поливалка"}

    response = await api.post("/api/import", json={"bundle": bundle})
    assert response.status_code == 409
    assert len((await api.get("/api/machines")).json()) == 1


async def test_broken_file_is_rejected(api: httpx.AsyncClient) -> None:
    response = await api.post("/api/import/preview", json={"format": "something else"})
    assert response.status_code == 422
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    created = await machine(api, tank, pump, calibrated=False)
    bundle = (await api.get("/api/export")).json()
    bundle["catalog"]["tank"] = {}
    response = await api.post("/api/import/preview", json=bundle)
    assert response.status_code == 422
    assert created["id"]
