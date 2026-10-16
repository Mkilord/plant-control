"""Тесты справочников: общие записи, копирование машин, устаревшая калибровка, миграция."""

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx

from plant_control_addon.api.app import DB_NAME, create_app
from plant_control_addon.storage import MachineStore
from tests.conftest import FakeGateway, running, settings
from tests.test_machines_api import wait_idle

TANK: dict[str, Any] = {
    "name": "Ведро 10 л",
    "geometry": {"shape": "measured", "volume_ml": 10000, "height_mm": 200},
    "reserve_ml": 0,
}
PUMP = {"name": "Насос 12 В", "max_runtime_s": 60}
CALIBRATION = {
    "flow_points": [{"tank_volume_ml": 10000, "flow_ml_s": 1000}],
    "prime_s": 0,
    "afterflow_ml": 0,
    "method": "manual",
}


async def add(api: httpx.AsyncClient, kind: str, body: dict[str, Any]) -> str:
    response = await api.post(f"/api/catalog/{kind}", json=body)
    assert response.status_code == 201, response.text
    item_id: str = response.json()["id"]
    return item_id


async def machine(
    api: httpx.AsyncClient,
    tank: str,
    pump: str,
    *,
    name: str = "Поливалка",
    entity: str = "switch.pump_1",
    calibrated: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    route: dict[str, Any] = {"id": "main", "connection": {"length_mm": 700, "inner_diameter_mm": 4}}
    if calibrated:
        route["calibration"] = CALIBRATION
    body = {
        "name": name,
        "tank_type": tank,
        "pump": {"model": pump, "entity_id": entity},
        "plumbing": {"type": "direct", "back_to_tank_fraction": 0},
        "routes": [route],
        **extra,
    }
    response = await api.post("/api/machines", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def water(api: httpx.AsyncClient, machine_id: str, dose: float = 100) -> httpx.Response:
    return await api.post(
        f"/api/machines/{machine_id}/water", json={"route_id": "main", "dose_ml": dose}
    )


# --- Справочники ---


async def test_catalog_crud_and_usage(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    created = await machine(api, tank, pump)

    listing = (await api.get("/api/catalog")).json()
    assert [item["id"] for item in listing["tank"]] == [tank]
    assert listing["tank"][0]["users"] == [
        {"machine_id": created["id"], "name": "Поливалка", "routes": []}
    ]

    response = await api.delete(f"/api/catalog/tank/{tank}")
    assert response.status_code == 409
    assert response.json()["machines"] == ["Поливалка"]

    await api.delete(f"/api/machines/{created['id']}")
    assert (await api.delete(f"/api/catalog/tank/{tank}")).status_code == 204
    assert (await api.get(f"/api/catalog/tank/{tank}")).status_code == 404


async def test_invalid_item_is_422(api: httpx.AsyncClient) -> None:
    response = await api.post("/api/catalog/collector", json={"name": "Один", "outlets": 1})
    assert response.status_code == 422


async def test_machine_with_unknown_reference_is_rejected(api: httpx.AsyncClient) -> None:
    pump = await add(api, "pump", PUMP)
    response = await api.post(
        "/api/machines",
        json={
            "name": "x",
            "tank_type": "tank-nope",
            "pump": {"model": pump, "entity_id": "switch.pump_1"},
            "plumbing": {"type": "direct"},
            "routes": [{"id": "main", "connection": {"length_mm": 1, "inner_diameter_mm": 4}}],
        },
    )
    assert response.status_code == 404


async def test_shared_tank_change_applies_to_every_machine(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    first = await machine(api, tank, pump, calibrated=False)
    second = await machine(api, tank, pump, name="Вторая", entity="switch.pump_2", calibrated=False)

    bigger = {**TANK, "geometry": {"shape": "measured", "volume_ml": 20000, "height_mm": 200}}
    response = await api.put(f"/api/catalog/tank/{tank}", json=bigger)
    assert response.status_code == 200, response.text

    for created in (first, second):
        body = (await api.get(f"/api/machines/{created['id']}")).json()
        assert body["status"]["tank"]["capacity_ml"] == 20000


async def test_one_entity_cannot_serve_two_machines(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    await machine(api, tank, pump)
    response = await api.post(
        "/api/machines",
        json={
            "name": "Вторая",
            "tank_type": tank,
            "pump": {"model": pump, "entity_id": "switch.pump_1"},
            "plumbing": {"type": "direct"},
            "routes": [{"id": "main", "connection": {"length_mm": 1, "inner_diameter_mm": 4}}],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == "EntityInUseError"


async def test_collector_must_have_enough_outlets(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    collector = await add(api, "collector", {"name": "На 2", "outlets": 2})
    routes = [
        {
            "id": f"v{i}",
            "valve_entity_id": f"input_boolean.valve_{i}",
            "connection": {"length_mm": 300, "inner_diameter_mm": 4},
        }
        for i in (1, 2, 3)
    ]
    response = await api.post(
        "/api/machines",
        json={
            "name": "Три растения",
            "tank_type": tank,
            "pump": {"model": pump, "entity_id": "switch.pump_1"},
            "plumbing": {
                "type": "collector",
                "collector_type": collector,
                "supply": {"length_mm": 500, "inner_diameter_mm": 4},
            },
            "routes": routes,
        },
    )
    assert response.status_code == 422
    assert "outlets" in response.json()["detail"]


async def test_pump_limit_can_be_switched_off(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", {**TANK, "geometry": {**TANK["geometry"], "volume_ml": 99000}})
    unlimited = await add(api, "pump", {"name": "Без предела", "max_runtime_s": None})
    default = (await api.get(f"/api/catalog/pump/{await add(api, 'pump', {'name': 'x'})}")).json()
    assert default["item"]["max_runtime_s"] == 300

    created = await machine(api, tank, unlimited)
    # 400 секунд при расходе 1000 мл/с: больше предела по умолчанию, но предел выключен.
    response = await api.post(
        f"/api/machines/{created['id']}/plan", json={"route_id": "main", "dose_ml": 400_000}
    )
    assert response.status_code == 409  # воды не хватит, но не из-за предела
    assert response.json()["error"] == "NotEnoughWaterError"


# --- Копирование ---


async def test_copy_keeps_calibration_and_waters_right_away(
    api: httpx.AsyncClient, gateway: FakeGateway
) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    source = await machine(api, tank, pump)

    response = await api.post(
        f"/api/machines/{source['id']}/copy",
        json={"name": "Копия", "pump_entity_id": "switch.pump_2"},
    )
    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["config"]["pump"] == {"model": pump, "entity_id": "switch.pump_2"}
    flow = copy["status"]["flows"][0]
    assert flow["source"] == "own"
    assert flow["copied_from"] == "Поливалка"
    assert not flow["stale"]

    response = await water(api, copy["id"])
    assert response.status_code == 202, response.text
    await wait_idle(api, copy["id"])
    assert "turn_on switch.pump_2" in gateway.commands()


async def test_copy_needs_its_own_relays(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    source = await machine(api, tank, pump)
    response = await api.post(
        f"/api/machines/{source['id']}/copy",
        json={"name": "Копия", "pump_entity_id": "switch.pump_1"},
    )
    assert response.status_code == 409


# --- Устаревшая калибровка ---


async def test_changed_tube_makes_calibration_stale(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    created = await machine(api, tank, pump)
    machine_id = created["id"]

    config = created["config"]
    config["routes"][0]["connection"]["length_mm"] = 1500
    response = await api.put(f"/api/machines/{machine_id}", json=config)
    assert response.status_code == 200, response.text
    assert response.json()["status"]["flows"][0]["stale"]
    blockers = response.json()["status"]["blockers"]
    assert [b["kind"] for b in blockers] == ["calibration_stale"]

    response = await water(api, machine_id)
    assert response.status_code == 409

    response = await api.post(f"/api/machines/{machine_id}/routes/main/calibration/accept")
    assert response.status_code == 200, response.text
    assert not response.json()["status"]["flows"][0]["stale"]
    assert (await water(api, machine_id)).status_code == 202
    await wait_idle(api, machine_id)

    history = (await api.get(f"/api/machines/{machine_id}/calibrations")).json()
    assert history[0]["method"] == "accepted"


async def test_renaming_or_rebinding_keeps_calibration(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    created = await machine(api, tank, pump)
    config = created["config"]
    config["name"] = "Другое имя"
    config["pump"]["entity_id"] = "switch.pump_2"
    response = await api.put(f"/api/machines/{created['id']}", json=config)
    assert not response.json()["status"]["flows"][0]["stale"]


async def test_tank_type_change_is_previewed_and_marks_stale(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    created = await machine(api, tank, pump)

    changed = {**TANK, "reserve_ml": 1000}
    preview = (await api.post(f"/api/catalog/tank/{tank}/preview", json=changed)).json()
    assert preview == [{"machine_id": created["id"], "name": "Поливалка", "stale_routes": ["main"]}]
    # Предпросмотр ничего не меняет.
    body = (await api.get(f"/api/machines/{created['id']}")).json()
    assert not body["status"]["flows"][0]["stale"]

    renamed = {**TANK, "name": "Новое имя"}
    preview = (await api.post(f"/api/catalog/tank/{tank}/preview", json=renamed)).json()
    assert preview[0]["stale_routes"] == []

    await api.put(f"/api/catalog/tank/{tank}", json=changed)
    body = (await api.get(f"/api/machines/{created['id']}")).json()
    assert body["status"]["flows"][0]["stale"]


async def test_pump_limits_do_not_affect_calibration(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    created = await machine(api, tank, pump)
    await api.put(f"/api/catalog/pump/{pump}", json={**PUMP, "max_runtime_s": 120})
    body = (await api.get(f"/api/machines/{created['id']}")).json()
    assert not body["status"]["flows"][0]["stale"]


# --- Расписания и группы ---

DAILY = {"type": "weekly", "days": [0, 1, 2, 3, 4, 5, 6], "times": ["08:00"]}


async def test_schedule_template_dose_beats_plant_dose(api: httpx.AsyncClient) -> None:
    tank = await add(api, "tank", TANK)
    pump = await add(api, "pump", PUMP)
    created = await machine(api, tank, pump)
    template = await add(api, "schedule", {"name": "Каждый день", "rule": DAILY})

    url = f"/api/machines/{created['id']}/routes/main/schedule-link"
    body = (await api.put(url, json={"template": template})).json()
    schedule = body["status"]["schedules"][0]
    assert schedule["template"] == template
    assert schedule["dose_ml"] == 100  # доза растения по умолчанию

    await api.put(
        f"/api/catalog/schedule/{template}",
        json={"name": "Каждый день", "rule": DAILY, "dose_ml": 250},
    )
    body = (await api.get(f"/api/machines/{created['id']}")).json()
    assert body["status"]["schedules"][0]["dose_ml"] == 250

    users = (await api.get(f"/api/catalog/schedule/{template}")).json()["users"]
    assert users[0]["routes"] == ["main"]

    # Своё расписание заменяет ссылку.
    own = {"rule": DAILY, "dose_ml": 50}
    body = (await api.put(f"/api/machines/{created['id']}/routes/main/schedule", json=own)).json()
    assert body["status"]["schedules"][0]["template"] is None
    assert body["config"]["routes"][0]["schedule_link"] is None


async def test_power_group_from_catalog_waters_one_by_one(
    gateway: FakeGateway, tmp_path: Path
) -> None:
    app = create_app(
        ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False, queue_tick=0.02
    )
    async with running(app) as api:
        tank = await add(api, "tank", TANK)
        slow = await add(api, "pump", {"name": "Медленный", "flow": None})
        group = await add(api, "power", {"name": "Блок 12 В", "max_concurrent": 1})
        slow_cal = {**CALIBRATION, "flow_points": [{"tank_volume_ml": 10000, "flow_ml_s": 200}]}

        ids = []
        for index, entity in enumerate(("switch.pump_1", "switch.pump_2")):
            created = await machine(
                api, tank, slow, name=f"M{index}", entity=entity, power_group=group
            )
            config = created["config"]
            config["routes"][0]["calibration"] = slow_cal
            await api.put(f"/api/machines/{created['id']}", json=config)
            ids.append(created["id"])

        for machine_id in ids:
            assert (await water(api, machine_id)).status_code == 202
        await asyncio.sleep(0.1)
        queue = (await api.get("/api/queue")).json()
        assert len(queue["running"]) == 1
        assert len(queue["queued"]) == 1
        for machine_id in ids:
            await wait_idle(api, machine_id)


# --- Проверка реле ---


async def test_pulse_turns_relay_on_and_off(api: httpx.AsyncClient, gateway: FakeGateway) -> None:
    response = await api.post("/api/ha/entities/switch.pump_2/pulse", json={"seconds": 0.2})
    assert response.status_code == 204
    assert gateway.commands() == ["turn_on switch.pump_2", "turn_off switch.pump_2"]


# --- Миграция ---

LEGACY_COLLECTOR: dict[str, Any] = {
    "name": "Старая",
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
    "plumbing": {"type": "collector", "supply": {"length_mm": 500, "inner_radius_mm": 2}},
    "routes": [
        {
            "id": "v1",
            "valve_entity_id": "input_boolean.valve_1",
            "connection": {"length_mm": 300, "inner_diameter_mm": 4},
            "calibration": CALIBRATION,
        },
        {
            "id": "v2",
            "valve_entity_id": "input_boolean.valve_2",
            "connection": {"length_mm": 300, "inner_diameter_mm": 4},
        },
    ],
    "flow_mode": "calibrated",
    "timings": {"valve_lead_s": 0, "valve_lag_s": 0},
    "power_group": "psu",
    "power_limit": 2,
    "power_gap_s": 1,
}


async def test_legacy_machines_move_to_the_catalog(gateway: FakeGateway, tmp_path: Path) -> None:
    store = MachineStore(tmp_path / DB_NAME)
    await store.open()
    second = {
        **LEGACY_COLLECTOR,
        "name": "Вторая старая",
        "pump": {**LEGACY_COLLECTOR["pump"], "entity_id": "switch.pump_2"},
        "routes": [
            {**route, "valve_entity_id": f"input_boolean.valve_{i + 3}"}
            for i, route in enumerate(LEGACY_COLLECTOR["routes"])
        ],
        "power_limit": 1,
        "power_gap_s": 3,
    }
    with sqlite3.connect(tmp_path / DB_NAME) as db:
        for machine_id, config in (("m-old1", LEGACY_COLLECTOR), ("m-old2", second)):
            db.execute(
                "INSERT INTO machines VALUES (?, ?, ?, ?, ?)",
                (machine_id, json.dumps(config), "{}", "2026-01-01", "2026-01-01"),
            )

    app = create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    async with running(app) as api:
        catalog = (await api.get("/api/catalog")).json()
        # Одинаковые бак, насос и коллектор схлопнулись в одну запись.
        assert len(catalog["tank"]) == 1
        assert len(catalog["pump"]) == 1
        assert len(catalog["collector"]) == 1
        assert catalog["collector"][0]["item"]["outlets"] == 2
        assert catalog["collector"][0]["item"]["valve_lead_s"] == 0
        group = catalog["power"][0]["item"]
        assert (group["name"], group["max_concurrent"], group["min_start_gap_s"]) == ("psu", 1, 3)

        body = (await api.get("/api/machines/m-old1")).json()
        assert body["config"]["tank_type"] == catalog["tank"][0]["id"]
        assert body["config"]["plumbing"]["supply"]["inner_diameter_mm"] == 4
        flows = {f["route_id"]: f for f in body["status"]["flows"]}
        assert flows["v1"]["source"] == "own"
        assert not flows["v1"]["stale"]
        assert flows["v2"]["source"] == "inherited"
        assert body["status"]["blockers"] == []

    # Второй запуск: миграция уже прошла, новые записи не появляются.
    app = create_app(ha=gateway, settings=settings(), data_dir=tmp_path, mqtt=False)
    async with running(app) as api:
        catalog = (await api.get("/api/catalog")).json()
        assert len(catalog["tank"]) == 1
        body = (await api.get("/api/machines/m-old2")).json()
        assert not body["status"]["flows"][0]["stale"]
