"""Общие шаги управления насосом и клапанами для сервисов.

Каждый шаг: вызвать порт, при успехе отметить факт в модели,
при сбое отметить "неизвестно". Выключение и закрытие никогда не бросают:
они возвращают ошибку, чтобы вызывающий код успел выполнить остальные шаги
аварийной остановки и только потом сообщил о проблеме.
"""

from plant_control.application.ports import (
    Clock,
    PumpControlError,
    PumpControlPort,
    ValveControlError,
    ValveControlPort,
)
from plant_control.domain.collector import Collector, ValveState
from plant_control.domain.pump import Pump, PumpState


class Actuation:
    def __init__(self, pumps: PumpControlPort, valves: ValveControlPort, clock: Clock) -> None:
        self._pumps = pumps
        self._valves = valves
        self._clock = clock

    async def start_pump(self, pump: Pump) -> None:
        """Включить насос. Проверки правил - забота вызывающего кода."""
        try:
            await self._pumps.turn_on(pump.id)
        except PumpControlError:
            pump.mark_unknown()
            raise
        pump.mark_started(self._clock.now())

    async def stop_pump(self, pump: Pump, *, force: bool = False) -> PumpControlError | None:
        """Выключить насос, если он не выключен (или всегда при force).

        Возвращает ошибку порта вместо того, чтобы её бросить.
        """
        if pump.state is PumpState.OFF and not force:
            return None
        try:
            await self._pumps.turn_off(pump.id)
        except PumpControlError as error:
            pump.mark_unknown()
            return error
        pump.mark_stopped(self._clock.now())
        return None

    async def open_valve(self, collector: Collector, valve_id: str) -> None:
        try:
            await self._valves.open(valve_id)
        except ValveControlError:
            collector.mark_unknown(valve_id)
            raise
        collector.mark_opened(valve_id)

    async def close_valve(
        self, collector: Collector, valve_id: str, *, force: bool = False
    ) -> ValveControlError | None:
        """Закрыть клапан, если он не закрыт (или всегда при force)."""
        if collector.valve_state(valve_id) is ValveState.CLOSED and not force:
            return None
        try:
            await self._valves.close(valve_id)
        except ValveControlError as error:
            collector.mark_unknown(valve_id)
            return error
        collector.mark_closed(valve_id)
        return None
