"""Эндпоинты пуш-уведомлений: настройки, телефоны, тексты и проверочный пуш."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from plant_control.application.notifications import Event, EventKind
from pydantic import BaseModel

from plant_control_addon.ha.client import HomeAssistantError
from plant_control_addon.notification_settings import (
    EventText,
    NotificationSettings,
    NotificationSettingsManager,
)
from plant_control_addon.notifications import (
    MESSAGES,
    PLACEHOLDERS,
    TITLES,
    NoPushTargetsError,
    PushNotifier,
    Texts,
    message_for,
    title_for,
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class PushDevices(BaseModel):
    # Все телефоны с приложением HA.
    available: list[str]
    # Куда пуш уйдёт при текущих настройках.
    targets: list[str]


class PushTargets(BaseModel):
    enabled: bool
    devices: list[str]


class TemplateOut(BaseModel):
    """Текст по умолчанию и подстановки одного вида событий."""

    kind: EventKind
    title: str
    message: str
    placeholders: list[str]


class PreviewRequest(BaseModel):
    kind: EventKind
    text: EventText


class PreviewOut(BaseModel):
    title: str
    message: str


def _push(request: Request) -> PushNotifier:
    push: PushNotifier = request.app.state.push
    return push


def _settings(request: Request) -> NotificationSettingsManager:
    manager: NotificationSettingsManager = request.app.state.notification_settings
    return manager


@router.get("/settings")
async def get_settings(request: Request) -> NotificationSettings:
    return _settings(request).current


@router.put("/settings")
async def put_settings(body: NotificationSettings, request: Request) -> NotificationSettings:
    """Сохранить и сразу применить."""
    return await _settings(request).update(body)


@router.get("/devices")
async def push_devices(request: Request) -> PushDevices:
    """Телефоны с приложением HA и те, на которые уйдёт пуш."""
    push = _push(request)
    try:
        return PushDevices(available=await push.available(), targets=await push.targets())
    except HomeAssistantError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error


@router.get("/templates")
async def templates() -> list[TemplateOut]:
    return [
        TemplateOut(
            kind=kind,
            title=TITLES[kind],
            message=MESSAGES[kind],
            placeholders=list(PLACEHOLDERS[kind]),
        )
        for kind in EventKind
    ]


@router.post("/preview")
async def preview(body: PreviewRequest) -> PreviewOut:
    """Как будет выглядеть уведомление с этим текстом, на примере."""
    texts = Texts(titles={body.kind: body.text.title}, messages={body.kind: body.text.message})
    event = SAMPLES[body.kind]
    return PreviewOut(title=title_for(event, texts), message=message_for(event, texts))


@router.post("/test")
async def test_push(request: Request) -> PushTargets:
    """Проверочный пуш на выбранные телефоны. Правила и тихие часы не действуют."""
    push = _push(request)
    data = push.base_data()
    data["tag"] = "plant_control_test"
    try:
        devices = await push.push("PlantControl", "Проверка: пуш-уведомления работают.", data)
    except NoPushTargetsError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except HomeAssistantError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    return PushTargets(enabled=request.app.state.notifications.enabled, devices=devices)


_AT = datetime(2026, 6, 1, 9, 30, tzinfo=UTC)
SAMPLES: dict[EventKind, Event] = {
    EventKind.WATERING_DONE: Event(
        EventKind.WATERING_DONE, "m-1", "Фикус", _AT, {"route_id": "Монстера", "dose_ml": 120}
    ),
    EventKind.WATERING_FAILED: Event(
        EventKind.WATERING_FAILED,
        "m-1",
        "Фикус",
        _AT,
        {"route_id": "Монстера", "dose_ml": 120, "error": "реле не отвечает"},
    ),
    EventKind.PROBLEM_OPENED: Event(
        EventKind.PROBLEM_OPENED,
        "m-1",
        "Фикус",
        _AT,
        {"problem": "tank_empty", "details": "Вода закончилась, долейте бак"},
    ),
    EventKind.PROBLEM_CLOSED: Event(
        EventKind.PROBLEM_CLOSED, "m-1", "Фикус", _AT, {"problem": "tank_empty"}
    ),
    EventKind.SCHEDULE_SKIPPED: Event(
        EventKind.SCHEDULE_SKIPPED,
        "m-1",
        "Фикус",
        _AT,
        {"route_id": "Монстера", "reason": "recently_watered"},
    ),
}
