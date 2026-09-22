"""Сценарий полива по маршруту.

Порядок для машины с коллектором:
    открыть клапан, пауза, включить насос, ждать расчётное время,
    выключить насос, пауза, закрыть клапан.
Окно клапана шире окна насоса: насос никогда не давит в закрытый клапан.

Без коллектора: включить насос, ждать, выключить.

Что бы ни случилось по дороге (сбой реле, отмена задачи, ошибка), насос
выключается, а клапан закрывается: это делает блок finally.
"""

from dataclasses import dataclass
from datetime import timedelta

from plant_control.application.actuation import Actuation
from plant_control.application.ports import (
    Clock,
    MachineRepository,
    PumpControlPort,
    Sleeper,
    ValveControlPort,
)
from plant_control.domain.collector import ValveState
from plant_control.domain.machine import WateringMachine
from plant_control.domain.watering import WateringPlan


@dataclass(frozen=True, slots=True)
class WateringTimings:
    """Паузы между клапаном и насосом."""

    valve_lead: timedelta = timedelta(milliseconds=500)
    valve_lag: timedelta = timedelta(milliseconds=500)


class WateringService:
    def __init__(
        self,
        machines: MachineRepository,
        pumps: PumpControlPort,
        valves: ValveControlPort,
        clock: Clock,
        sleeper: Sleeper,
        timings: WateringTimings | None = None,
    ) -> None:
        self._machines = machines
        self._actuation = Actuation(pumps, valves, clock)
        self._clock = clock
        self._sleeper = sleeper
        self._timings = timings or WateringTimings()

    async def plan(self, machine_id: str, route_id: str, dose_ml: float) -> WateringPlan:
        """Только посчитать, ничего не включая. Удобно для проверки и отображения."""
        machine = await self._machines.get(machine_id)
        return machine.plan_watering(route_id, dose_ml, self._clock.now())

    async def water(self, machine_id: str, route_id: str, dose_ml: float) -> WateringPlan:
        machine = await self._machines.get(machine_id)

        # Правила домена. При нарушении ничего не включаем.
        plan = machine.plan_watering(route_id, dose_ml, self._clock.now())
        machine.begin_watering(plan)
        await self._machines.save(machine)

        valve_id = machine.valve_for(route_id)
        completed = False
        try:
            if valve_id is not None:
                assert machine.collector is not None
                await self._actuation.open_valve(machine.collector, valve_id)
                await self._sleeper.sleep(self._timings.valve_lead)

            await self._actuation.start_pump(machine.pump)
            await self._sleeper.sleep(plan.duration)
            completed = True
        finally:
            # Сюда попадаем и при успехе, и при любой ошибке, и при отмене задачи.
            errors = await self._shut_down(machine, valve_id)
            if completed:
                machine.complete_watering(plan)
            else:
                machine.abort_watering()
            await self._machines.save(machine)

        # Полив прошёл, но выключить насос или закрыть клапан не удалось.
        if errors:
            raise errors[0]
        return plan

    async def _shut_down(self, machine: WateringMachine, valve_id: str | None) -> list[Exception]:
        errors: list[Exception] = []
        pump_error = await self._actuation.stop_pump(machine.pump)
        if pump_error is not None:
            errors.append(pump_error)

        collector = machine.collector
        if valve_id is not None and collector is not None:
            if collector.valve_state(valve_id) is not ValveState.CLOSED:
                await self._sleeper.sleep(self._timings.valve_lag)
            valve_error = await self._actuation.close_valve(collector, valve_id)
            if valve_error is not None:
                errors.append(valve_error)
        return errors
