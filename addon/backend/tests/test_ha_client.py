"""Тесты клиента WebSocket API Home Assistant на поддельном HA."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from plant_control_addon.ha.client import (
    EntityState,
    HomeAssistantClient,
    HomeAssistantCommandError,
    HomeAssistantUnavailableError,
)
from tests.fake_ha import TOKEN, FakeHomeAssistant


@pytest.fixture
async def fake_ha() -> AsyncIterator[FakeHomeAssistant]:
    fake = FakeHomeAssistant()
    await fake.server.start_server()
    yield fake
    await fake.server.close()


async def connected_client(fake: FakeHomeAssistant, token: str = TOKEN) -> HomeAssistantClient:
    client = HomeAssistantClient(fake.url, token, command_timeout=1, reconnect_delay=0.05)
    await client.start()
    assert await client.wait_connected(timeout=2)
    return client


async def test_connects_and_reads_states(fake_ha: FakeHomeAssistant) -> None:
    fake_ha.add_entity("switch.pump_1", "off", "Pump 1")
    client = await connected_client(fake_ha)
    try:
        states = await client.get_states()
    finally:
        await client.stop()
    assert states == [EntityState("switch.pump_1", "off", "Pump 1")]


async def test_calls_service(fake_ha: FakeHomeAssistant) -> None:
    fake_ha.add_entity("switch.pump_1", "off")
    client = await connected_client(fake_ha)
    try:
        await client.call_service("switch", "turn_on", "switch.pump_1")
    finally:
        await client.stop()
    assert fake_ha.service_calls == [("switch", "turn_on", "switch.pump_1")]


async def test_service_error_is_raised(fake_ha: FakeHomeAssistant) -> None:
    fake_ha.fail_services = True
    client = await connected_client(fake_ha)
    try:
        with pytest.raises(HomeAssistantCommandError, match="device offline"):
            await client.call_service("switch", "turn_on", "switch.pump_1")
    finally:
        await client.stop()


async def test_state_changes_reach_listeners(fake_ha: FakeHomeAssistant) -> None:
    fake_ha.add_entity("switch.pump_1", "off")
    client = await connected_client(fake_ha)
    received: list[tuple[str, str | None]] = []
    client.add_state_listener(
        lambda entity_id, state: received.append((entity_id, state.state if state else None))
    )
    try:
        # Подписка оформляется в фоне сразу после подключения.
        for _ in range(50):
            if fake_ha.subscriptions:
                break
            await asyncio.sleep(0.01)
        await fake_ha.set_state("switch.pump_1", "on")
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0.01)
    finally:
        await client.stop()
    assert received == [("switch.pump_1", "on")]


async def test_invalid_token_stops_reconnecting(fake_ha: FakeHomeAssistant) -> None:
    client = HomeAssistantClient(fake_ha.url, "bad", command_timeout=1, reconnect_delay=0.05)
    await client.start()
    try:
        assert not await client.wait_connected(timeout=0.5)
        assert client.auth_error == "Invalid access token"
    finally:
        await client.stop()


async def test_command_without_connection_fails_fast() -> None:
    client = HomeAssistantClient("ws://127.0.0.1:1/api/websocket", TOKEN)
    with pytest.raises(HomeAssistantUnavailableError):
        await client.get_states()


async def test_reconnects_after_connection_drop(fake_ha: FakeHomeAssistant) -> None:
    fake_ha.add_entity("switch.pump_1", "off")
    client = await connected_client(fake_ha)
    try:
        await fake_ha.drop_connections()
        for _ in range(100):
            if not client.is_connected:
                break
            await asyncio.sleep(0.01)
        assert await client.wait_connected(timeout=2)
        assert len(await client.get_states()) == 1
    finally:
        await client.stop()
