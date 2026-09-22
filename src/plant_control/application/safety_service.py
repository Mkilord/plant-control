"""Безопасность: аварийная остановка, безопасный старт, сторож насоса.

Сторож не держит таймер сам: инфраструктура вызывает check_overrun по дедлайну
или периодически, а observe_pump_state - когда HA сообщает о смене состояния реле.
"""

from plant_control.application.actuation import Actuation
from plant_control.application.ports import (
    Clock,
    MachineRepository,
    PumpControlPort,
    ValveControlPort,
)
from plant_control.domain.machine import WateringMachine
from plant_control.domain.pump import PumpState


class SafetyService:
    def __init__(
        self,
        machines: MachineRepository,
        pumps: PumpControlPort,
        valves: ValveControlPort,
        clock: Clock,
    ) -> None:
        self._machines = machines
        self._actuation = Actuation(pumps, valves, clock)
        self._clock = clock

    async def safe_start(self, machine_id: str) -> list[Exception]:
        """При запуске: выключить насос и закрыть все клапаны, не веря модели.

        После перезапуска модель могла отстать от реальности, поэтому команды
        отправляются всегда (force). Возвращает ошибки портов, если были.
        """
        machine = await self._machines.get(machine_id)
        errors = await self._stop_everything(machine, force=True)
        machine.abort_watering()
        await self._machines.save(machine)
        return errors

    async def emergency_stop(self, machine_id: str) -> list[Exception]:
        """Выключить насос и закрыть всё, что не закрыто."""
        machine = await self._machines.get(machine_id)
        errors = await self._stop_everything(machine, force=False)
        await self._machines.save(machine)
        return errors

    async def check_overrun(self, machine_id: str) -> bool:
        """Сторож: если насос работает дольше предела, аварийно остановить.

        Возвращает True, если остановка понадобилась.
        """
        machine = await self._machines.get(machine_id)
        if not machine.pump.is_overrun(self._clock.now()):
            return False
        await self._stop_everything(machine, force=False)
        await self._machines.save(machine)
        return True

    async def observe_pump_state(self, machine_id: str, is_on: bool) -> None:
        """HA сообщил фактическое состояние реле насоса: синхронизировать модель.

        Так модель узнаёт и о ручном включении или выключении из интерфейса HA.
        """
        machine = await self._machines.get(machine_id)
        pump = machine.pump
        now = self._clock.now()
        if is_on and pump.state is not PumpState.ON:
            pump.mark_started(now)
        elif not is_on and pump.state is not PumpState.OFF:
            pump.mark_stopped(now)
        await self._machines.save(machine)

    async def _stop_everything(self, machine: WateringMachine, *, force: bool) -> list[Exception]:
        errors: list[Exception] = []
        pump_error = await self._actuation.stop_pump(machine.pump, force=force)
        if pump_error is not None:
            errors.append(pump_error)
        collector = machine.collector
        if collector is not None:
            for valve_id in collector.valve_ids:
                valve_error = await self._actuation.close_valve(collector, valve_id, force=force)
                if valve_error is not None:
                    errors.append(valve_error)
        return errors
