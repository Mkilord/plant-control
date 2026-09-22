"""Порты: интерфейсы, которые реализует инфраструктура."""

from datetime import datetime, timedelta
from typing import Protocol

from plant_control.domain.machine import WateringMachine
from plant_control.domain.pump import Pump

# --- Ошибки инфраструктуры ---
# Не доменные: реле не ответило, HA недоступен и так далее.


class PumpControlError(Exception):
    pass


class ValveControlError(Exception):
    pass


# --- Исполнительные устройства ---


class PumpControlPort(Protocol):
    async def turn_on(self, pump_id: str) -> None: ...

    async def turn_off(self, pump_id: str) -> None: ...


class ValveControlPort(Protocol):
    async def open(self, valve_id: str) -> None: ...

    async def close(self, valve_id: str) -> None: ...


# --- Время ---


class Clock(Protocol):
    def now(self) -> datetime: ...


class Sleeper(Protocol):
    """Ожидание. В HA - asyncio.sleep, в тестах - мгновенно и с записью."""

    async def sleep(self, duration: timedelta) -> None: ...


# --- Хранение ---


class PumpRepository(Protocol):
    async def get(self, pump_id: str) -> Pump: ...

    async def save(self, pump: Pump) -> None: ...


class MachineRepository(Protocol):
    async def get(self, machine_id: str) -> WateringMachine: ...

    async def save(self, machine: WateringMachine) -> None: ...
