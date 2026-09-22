"""Адаптеры портов ядра поверх Home Assistant.

Ядро знает только свои id насосов и клапанов. Какая сущность HA за ними стоит,
решает функция resolve: pump-1 -> switch.pump_1. Её дают хранилище или настройки.
"""

from collections.abc import Callable
from typing import Protocol

from plant_control.application.ports import PumpControlError, ValveControlError

from plant_control_addon.ha.client import HomeAssistantError

# Какими сущностями HA можно управлять как реле.
# input_boolean удобен для проверки без железа: это переключатель-помощник в HA.
SWITCHABLE_DOMAINS = frozenset({"switch", "input_boolean"})


class ServiceCaller(Protocol):
    async def call_service(self, domain: str, service: str, entity_id: str) -> None: ...


def domain_of(entity_id: str) -> str:
    domain, _, name = entity_id.partition(".")
    if not name or domain not in SWITCHABLE_DOMAINS:
        raise ValueError(f"{entity_id!r} is not a switchable entity")
    return domain


async def switch(client: ServiceCaller, entity_id: str, on: bool) -> None:
    await client.call_service(domain_of(entity_id), "turn_on" if on else "turn_off", entity_id)


class HaPumpControl:
    """Реализация PumpControlPort."""

    def __init__(self, client: ServiceCaller, resolve: Callable[[str], str]) -> None:
        self._client = client
        self._resolve = resolve

    async def turn_on(self, pump_id: str) -> None:
        await self._switch(pump_id, on=True)

    async def turn_off(self, pump_id: str) -> None:
        await self._switch(pump_id, on=False)

    async def _switch(self, pump_id: str, *, on: bool) -> None:
        try:
            await switch(self._client, self._resolve(pump_id), on)
        except (HomeAssistantError, KeyError, ValueError) as error:
            raise PumpControlError(f"pump {pump_id!r}: {error}") from error


class HaValveControl:
    """Реализация ValveControlPort."""

    def __init__(self, client: ServiceCaller, resolve: Callable[[str], str]) -> None:
        self._client = client
        self._resolve = resolve

    async def open(self, valve_id: str) -> None:
        await self._switch(valve_id, on=True)

    async def close(self, valve_id: str) -> None:
        await self._switch(valve_id, on=False)

    async def _switch(self, valve_id: str, *, on: bool) -> None:
        try:
            await switch(self._client, self._resolve(valve_id), on)
        except (HomeAssistantError, KeyError, ValueError) as error:
            raise ValveControlError(f"valve {valve_id!r}: {error}") from error
