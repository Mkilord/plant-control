"""Эндпоинты для работы с сущностями Home Assistant.

Нужны интерфейсу, чтобы выбирать реле насосов и клапанов из списка,
и для первой проверки на железе: включить и выключить реле руками.
"""

from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from plant_control_addon.ha.client import (
    ConnectListener,
    EntityState,
    HomeAssistantError,
    StateListener,
)
from plant_control_addon.ha.devices import SWITCHABLE_DOMAINS, switch


class HaGateway(Protocol):
    """То, что API нужно от клиента HA. В тестах подменяется фейком."""

    @property
    def is_connected(self) -> bool: ...

    async def get_states(self) -> list[EntityState]: ...

    async def get_services(self) -> dict[str, dict[str, Any]]: ...

    async def call_service(self, domain: str, service: str, entity_id: str) -> None: ...

    async def call_service_data(self, domain: str, service: str, data: dict[str, Any]) -> None: ...

    async def fire_event(self, event_type: str, data: dict[str, Any]) -> None: ...

    def add_state_listener(self, listener: StateListener) -> None: ...

    def add_connect_listener(self, listener: ConnectListener) -> None: ...


def get_ha(request: Request) -> HaGateway:
    # Клиент кладётся в app.state при старте приложения.
    ha: HaGateway = request.app.state.ha
    return ha


# Annotated[..., Depends(...)] - внедрение зависимости, как @Autowired в параметре.
Ha = Annotated[HaGateway, Depends(get_ha)]


class EntityOut(BaseModel):
    entity_id: str
    domain: str
    name: str
    state: str


router = APIRouter(prefix="/api/ha", tags=["home-assistant"])


@router.get("/entities")
async def list_switchable_entities(ha: Ha) -> list[EntityOut]:
    """Сущности, которые годятся как реле насоса или клапана."""
    try:
        states = await ha.get_states()
    except HomeAssistantError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    return sorted(
        (
            EntityOut(entity_id=s.entity_id, domain=s.domain, name=s.friendly_name, state=s.state)
            for s in states
            if s.domain in SWITCHABLE_DOMAINS
        ),
        key=lambda e: e.entity_id,
    )


@router.post("/entities/{entity_id}/turn_on", status_code=status.HTTP_204_NO_CONTENT)
async def turn_on(entity_id: str, ha: Ha) -> None:
    await _switch(ha, entity_id, on=True)


@router.post("/entities/{entity_id}/turn_off", status_code=status.HTTP_204_NO_CONTENT)
async def turn_off(entity_id: str, ha: Ha) -> None:
    await _switch(ha, entity_id, on=False)


async def _switch(ha: HaGateway, entity_id: str, *, on: bool) -> None:
    try:
        await switch(ha, entity_id, on)
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
    except HomeAssistantError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
