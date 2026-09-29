"""Настройки уведомлений, которые правятся в интерфейсе.

Лежат в базе рядом с машинами, поэтому переживают перезапуск и обновление.
Применяются сразу: сервис уведомлений и пуш перенастраиваются на ходу.
"""

import logging
import re
from datetime import time
from typing import Annotated, Protocol

from plant_control.application.notifications import (
    DEFAULT_KINDS,
    EventKind,
    NotificationRules,
    NotificationService,
)
from pydantic import BaseModel, Field, field_validator

from plant_control_addon.notifications import DEFAULT_TEXTS, PushNotifier, Texts, check_template

log = logging.getLogger(__name__)

# "23:00", "7:30". Пусто - тихих часов нет.
TIME_PATTERN = r"^([01]?\d|2[0-3]):[0-5]\d$"
Clock = Annotated[str, Field(pattern=f"{TIME_PATTERN}|^$")]


class EventText(BaseModel):
    """Свой текст одного вида событий. Пусто - текст по умолчанию."""

    title: str = Field(default="", max_length=120)
    message: str = Field(default="", max_length=500)

    @field_validator("title", "message")
    @classmethod
    def known_placeholders(cls, value: str) -> str:
        unknown = check_template(value)
        if unknown:
            names = ", ".join("{" + name + "}" for name in unknown)
            raise ValueError(f"unknown placeholders: {names}")
        return value


class NotificationSettings(BaseModel):
    enabled: bool = True
    # Телефоны: mobile_app_pixel_7. Пусто - все телефоны с приложением HA.
    devices: list[str] = []
    # Срочное - критическим пушем: звучит и в беззвучном режиме.
    critical: bool = False
    # О чём сообщать.
    events: list[EventKind] = sorted(DEFAULT_KINDS, key=lambda kind: kind.value)
    quiet_from: Clock = ""
    quiet_to: Clock = ""
    # Расширенные настройки: свои тексты и адрес по нажатию.
    # Выключены - действуют тексты по умолчанию, а сохранённые ждут своего часа.
    advanced: bool = False
    texts: dict[EventKind, EventText] = {}
    open_url: str = Field(default="", max_length=500)

    @field_validator("devices")
    @classmethod
    def clean_devices(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for device in value:
            name = device.strip().removeprefix("notify.")
            if not re.fullmatch(r"\w+", name):
                raise ValueError(f"bad notify service name {device!r}")
            if name not in cleaned:
                cleaned.append(name)
        return cleaned

    def rules(self, timezone: str) -> NotificationRules:
        return NotificationRules(
            kinds=frozenset(self.events),
            quiet_from=_time(self.quiet_from),
            quiet_to=_time(self.quiet_to),
            timezone=timezone,
        )

    def custom_texts(self) -> Texts:
        if not self.advanced:
            return DEFAULT_TEXTS
        return Texts(
            titles={kind: text.title for kind, text in self.texts.items()},
            messages={kind: text.message for kind, text in self.texts.items()},
        )


def apply(
    settings: NotificationSettings,
    service: NotificationService,
    push: PushNotifier,
    *,
    timezone: str,
    panel_url: str | None,
) -> None:
    """Перенастроить доставку по новым настройкам."""
    open_url = settings.open_url.strip() if settings.advanced else ""
    push.configure(
        settings.devices,
        open_url=open_url or panel_url,
        critical=settings.critical,
        texts=settings.custom_texts(),
    )
    service.configure(push if settings.enabled else None, settings.rules(timezone))


def _time(value: str) -> time | None:
    if not value:
        return None
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


class SettingsStore(Protocol):
    async def load_setting(self, key: str) -> str | None: ...

    async def save_setting(self, key: str, value_json: str) -> None: ...


SETTINGS_KEY = "notifications"


class NotificationSettingsManager:
    """Хранит настройки уведомлений и применяет их при загрузке и каждой правке."""

    def __init__(
        self,
        store: SettingsStore,
        service: NotificationService,
        push: PushNotifier,
        *,
        timezone: str,
        panel_url: str | None,
    ) -> None:
        self._store = store
        self._service = service
        self._push = push
        self._timezone = timezone
        self.panel_url = panel_url
        self.current = NotificationSettings()

    async def load(self) -> NotificationSettings:
        raw = await self._store.load_setting(SETTINGS_KEY)
        if raw is not None:
            try:
                self.current = NotificationSettings.model_validate_json(raw)
            except ValueError:
                log.exception("stored notification settings are broken, using defaults")
        self._apply()
        return self.current

    async def update(self, settings: NotificationSettings) -> NotificationSettings:
        await self._store.save_setting(SETTINGS_KEY, settings.model_dump_json())
        self.current = settings
        self._apply()
        return settings

    def _apply(self) -> None:
        apply(
            self.current,
            self._service,
            self._push,
            timezone=self._timezone,
            panel_url=self.panel_url,
        )
