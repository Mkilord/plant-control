"""Наблюдения, которые видно только из инфраструктуры.

Ядро не знает про Home Assistant, поэтому проверку "жива ли связь" и "существует ли
сущность реле" делает add-on и передаёт результат в проверку состояния.
"""

import logging

from plant_control.domain.problems import Observation, ProblemKind

from plant_control_addon.api.ha_routes import HaGateway
from plant_control_addon.ha.client import HomeAssistantError
from plant_control_addon.registry import MachineRegistry

log = logging.getLogger(__name__)

# Состояния HA, при которых сущность есть, но ею нельзя управлять.
DEAD_STATES = frozenset({"unavailable", "unknown"})


class HaHealthSource:
    def __init__(self, ha: HaGateway, registry: MachineRegistry) -> None:
        self._ha = ha
        self._registry = registry

    async def observations(self) -> list[Observation]:
        entries = self._registry.entries()
        if not entries:
            return []

        if not self._ha.is_connected:
            return [
                Observation(
                    entry.id,
                    ProblemKind.HA_DISCONNECTED,
                    details="Нет связи с Home Assistant",
                )
                for entry in entries
            ]

        try:
            states = {state.entity_id: state.state for state in await self._ha.get_states()}
        except HomeAssistantError as error:
            log.warning("cannot read states for health check: %s", error)
            return [
                Observation(entry.id, ProblemKind.HA_DISCONNECTED, details=str(error))
                for entry in entries
            ]

        found: list[Observation] = []
        for entry in entries:
            pump_entity = entry.config.pump.entity_id
            if self._is_dead(states, pump_entity):
                found.append(
                    Observation(
                        entry.id,
                        ProblemKind.PUMP_ENTITY_MISSING,
                        target=pump_entity,
                        details=self._details(states, pump_entity),
                    )
                )
            for route in entry.config.routes:
                valve = route.valve_entity_id
                if valve is not None and self._is_dead(states, valve):
                    found.append(
                        Observation(
                            entry.id,
                            ProblemKind.VALVE_ENTITY_MISSING,
                            target=route.id,
                            details=self._details(states, valve),
                        )
                    )
        return found

    @staticmethod
    def _is_dead(states: dict[str, str], entity_id: str) -> bool:
        state = states.get(entity_id)
        return state is None or state in DEAD_STATES

    @staticmethod
    def _details(states: dict[str, str], entity_id: str) -> str:
        if entity_id not in states:
            return f"В Home Assistant нет сущности {entity_id}"
        return f"Сущность {entity_id} недоступна"
