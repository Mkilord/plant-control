from datetime import timedelta

from plant_control.application.ports import (
    Clock,
    PumpControlError,
    PumpControlPort,
    PumpRepository,
)


class PumpService:
    def __init__(
        self,
        control: PumpControlPort,
        repo: PumpRepository,
        clock: Clock,
    ) -> None:
        self._control = control
        self._repo = repo
        self._clock = clock

    async def start(self, pump_id: str, duration: timedelta) -> None:
        pump = await self._repo.get(pump_id)

        pump.check_can_start(self._clock.now(), duration)

        try:
            await self._control.turn_on(pump_id)
        except PumpControlError:
            pump.mark_unknown()
            await self._repo.save(pump)
            raise

        pump.mark_started(self._clock.now())
        await self._repo.save(pump)

    async def stop(self, pump_id: str) -> None:
        pump = await self._repo.get(pump_id)

        try:
            await self._control.turn_off(pump_id)
        except PumpControlError:
            pump.mark_unknown()
            await self._repo.save(pump)
            raise

        pump.mark_stopped(self._clock.now())
        await self._repo.save(pump)
