"""Фейковые реализации портов для тестов сервисов.

Все устройства пишут команды в один общий журнал, чтобы проверять порядок:
"клапан открыт, пауза, насос включён" и так далее.
"""

import asyncio
from datetime import datetime, timedelta

from plant_control.application.ports import PumpControlError, ValveControlError
from plant_control.domain.machine import WateringMachine


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class FakeSleeper:
    """Ждёт мгновенно, но двигает часы и пишет паузу в журнал.

    cancel_on - номер паузы (с 1), на которой изобразить отмену задачи.
    """

    def __init__(self, clock: FakeClock, log: list[str]) -> None:
        self._clock = clock
        self._log = log
        self.count = 0
        self.cancel_on: int | None = None

    async def sleep(self, duration: timedelta) -> None:
        self.count += 1
        self._log.append(f"sleep {duration.total_seconds():g}s")
        if self.count == self.cancel_on:
            raise asyncio.CancelledError
        self._clock.current += duration


class FakePumpControl:
    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.fail_on = False
        self.fail_off = False

    async def turn_on(self, pump_id: str) -> None:
        if self.fail_on:
            raise PumpControlError("relay unavailable")
        self._log.append(f"pump on {pump_id}")

    async def turn_off(self, pump_id: str) -> None:
        if self.fail_off:
            raise PumpControlError("relay unavailable")
        self._log.append(f"pump off {pump_id}")


class FakeValveControl:
    def __init__(self, log: list[str]) -> None:
        self._log = log
        self.fail_open = False
        self.fail_close = False

    async def open(self, valve_id: str) -> None:
        if self.fail_open:
            raise ValveControlError("valve unavailable")
        self._log.append(f"open {valve_id}")

    async def close(self, valve_id: str) -> None:
        if self.fail_close:
            raise ValveControlError("valve unavailable")
        self._log.append(f"close {valve_id}")


class InMemoryMachineRepository:
    def __init__(self, *machines: WateringMachine) -> None:
        self.machines: dict[str, WateringMachine] = {m.id: m for m in machines}
        self.saves = 0

    async def get(self, machine_id: str) -> WateringMachine:
        return self.machines[machine_id]

    async def save(self, machine: WateringMachine) -> None:
        self.machines[machine.id] = machine
        self.saves += 1
