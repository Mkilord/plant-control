"""Проверка состояния: что сейчас не так с машинами.

Проверка ничего не чинит и ничего не помнит. Она смотрит на машины и выдаёт срез
наблюдений, а доска проблем сама решает, что открыть и что закрыть.

Часть наблюдений ядро сделать не может: недоступна ли сущность в Home Assistant,
жива ли связь с ним. Их приносит инфраструктура через extra.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from plant_control.application.ports import Clock
from plant_control.domain.collector import ValveState
from plant_control.domain.machine import WateringMachine
from plant_control.domain.problems import Observation, Problem, ProblemBoard, ProblemKind
from plant_control.domain.pump import PumpState

# Доля бака, ниже которой считаем, что воды мало.
LOW_WATER_FRACTION = 0.15


class MachineDirectory(Protocol):
    """Откуда брать машины. Реестр add-on'а это умеет."""

    def machines(self) -> Sequence[WateringMachine]: ...


@dataclass(frozen=True, slots=True)
class HealthReport:
    opened: list[Problem]
    closed: list[Problem]
    active: list[Problem]


class HealthService:
    def __init__(
        self,
        directory: MachineDirectory,
        board: ProblemBoard,
        clock: Clock,
        *,
        low_water_fraction: float = LOW_WATER_FRACTION,
    ) -> None:
        self._directory = directory
        self._board = board
        self._clock = clock
        self._low_water_fraction = low_water_fraction

    @property
    def board(self) -> ProblemBoard:
        return self._board

    def check(self, extra: Iterable[Observation] = ()) -> HealthReport:
        """Снять срез состояния и обновить доску проблем."""
        now = self._clock.now()
        observations: list[Observation] = []
        for machine in self._directory.machines():
            observations.extend(self.inspect(machine, now))
        observations.extend(extra)
        opened, closed = self._board.observe(observations, now)
        return HealthReport(opened, closed, self._board.all())

    def inspect(self, machine: WateringMachine, now: datetime) -> list[Observation]:
        """Наблюдения по одной машине из её собственного состояния."""
        found: list[Observation] = []
        pump = machine.pump

        if pump.state is PumpState.UNKNOWN:
            found.append(
                Observation(
                    machine.id,
                    ProblemKind.PUMP_STATE_UNKNOWN,
                    details="Команда реле не подтвердилась, состояние насоса неизвестно",
                )
            )
        if pump.is_overrun(now):
            found.append(
                Observation(
                    machine.id,
                    ProblemKind.PUMP_OVERRUN,
                    details="Насос работает дольше предела из паспорта",
                )
            )

        collector = machine.collector
        if collector is not None:
            for valve_id in collector.valve_ids:
                if collector.valve_state(valve_id) is ValveState.UNKNOWN:
                    found.append(
                        Observation(
                            machine.id,
                            ProblemKind.VALVE_STATE_UNKNOWN,
                            target=valve_id,
                            details="Состояние клапана неизвестно",
                        )
                    )

        found.extend(self._water_observations(machine))
        return found

    def _water_observations(self, machine: WateringMachine) -> list[Observation]:
        tank = machine.tank
        usable = tank.usable_volume_ml
        if usable <= 0:
            return [
                Observation(
                    machine.id,
                    ProblemKind.TANK_EMPTY,
                    details="Вода закончилась, долейте бак",
                )
            ]
        capacity = tank.geometry.capacity_ml()
        if capacity > 0 and usable < capacity * self._low_water_fraction:
            return [
                Observation(
                    machine.id,
                    ProblemKind.TANK_LOW,
                    details=f"Осталось {usable:.0f} мл",
                )
            ]
        return []
