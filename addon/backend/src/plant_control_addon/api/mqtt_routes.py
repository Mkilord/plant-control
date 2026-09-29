"""Эндпоинты MQTT: настройки брокера и состояние соединения."""

from fastapi import APIRouter, Request

from plant_control_addon.mqtt.settings import (
    MqttManager,
    MqttSettingsIn,
    MqttSettingsOut,
    MqttStatus,
)

router = APIRouter(prefix="/api/mqtt", tags=["mqtt"])


def _manager(request: Request) -> MqttManager:
    manager: MqttManager = request.app.state.mqtt
    return manager


@router.get("/settings")
async def get_settings(request: Request) -> MqttSettingsOut:
    return _manager(request).current.public()


@router.put("/settings")
async def put_settings(body: MqttSettingsIn, request: Request) -> MqttSettingsOut:
    """Сохранить и переподключиться к брокеру. Пароль не передан - остаётся прежний."""
    settings = await _manager(request).update(body)
    return settings.public()


@router.get("/status")
async def status(request: Request) -> MqttStatus:
    return _manager(request).status()
