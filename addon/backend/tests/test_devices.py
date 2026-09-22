"""Тесты адаптеров насоса и клапана."""

import pytest
from plant_control.application.ports import PumpControlError, ValveControlError

from plant_control_addon.ha.client import HomeAssistantUnavailableError
from plant_control_addon.ha.devices import HaPumpControl, HaValveControl


class RecordingCaller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.fail = False

    async def call_service(self, domain: str, service: str, entity_id: str) -> None:
        if self.fail:
            raise HomeAssistantUnavailableError("offline")
        self.calls.append((domain, service, entity_id))


ENTITIES = {"pump-1": "switch.pump_1", "v1": "input_boolean.valve_1"}


async def test_pump_maps_id_to_entity() -> None:
    caller = RecordingCaller()
    pumps = HaPumpControl(caller, ENTITIES.__getitem__)
    await pumps.turn_on("pump-1")
    await pumps.turn_off("pump-1")
    assert caller.calls == [
        ("switch", "turn_on", "switch.pump_1"),
        ("switch", "turn_off", "switch.pump_1"),
    ]


async def test_valve_uses_entity_domain() -> None:
    caller = RecordingCaller()
    await HaValveControl(caller, ENTITIES.__getitem__).open("v1")
    assert caller.calls == [("input_boolean", "turn_on", "input_boolean.valve_1")]


async def test_ha_failure_becomes_pump_control_error() -> None:
    caller = RecordingCaller()
    caller.fail = True
    with pytest.raises(PumpControlError):
        await HaPumpControl(caller, ENTITIES.__getitem__).turn_on("pump-1")


async def test_unknown_pump_becomes_pump_control_error() -> None:
    with pytest.raises(PumpControlError):
        await HaPumpControl(RecordingCaller(), ENTITIES.__getitem__).turn_on("pump-9")


async def test_non_switchable_entity_is_rejected() -> None:
    with pytest.raises(ValveControlError):
        await HaValveControl(RecordingCaller(), {"v1": "sensor.temp"}.__getitem__).open("v1")
