"""Настройки add-on'а.

Два режима подключения к Home Assistant:
- внутри add-on'а: Supervisor сам кладёт токен в SUPERVISOR_TOKEN,
  а HA доступен по внутреннему адресу supervisor;
- при разработке: адрес HA и долгоживущий токен из .env или переменных окружения.
"""

import logging
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from plant_control.application.notifications import DEFAULT_KINDS, EventKind, NotificationRules
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

SUPERVISOR_WS_URL = "ws://supervisor/core/websocket"


class Settings(BaseSettings):
    # Аналог @ConfigurationProperties в Spring: поля читаются из окружения с префиксом.
    model_config = SettingsConfigDict(env_prefix="PLANT_CONTROL_", env_file=".env", extra="ignore")

    ha_url: str = ""
    ha_token: str = ""
    port: int = 8099
    # Где лежит база. В add-on'е это /data, её Supervisor сохраняет между обновлениями.
    data_dir: Path = Path("data")
    # Собранный фронт. Не задано - берётся папка static внутри пакета (так в add-on'е).
    static_dir: Path | None = None

    # MQTT: сущности машин в Home Assistant. Внутри add-on'а данные брокера
    # выдаёт Supervisor, при разработке их задают здесь.
    mqtt_enabled: bool = True
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    # Префикс, по которому Home Assistant ищет описания сущностей.
    mqtt_discovery_prefix: str = "homeassistant"
    # Уведомления в Home Assistant. persistent_notification.create есть всегда,
    # notify.<сервис> - телефон, телеграм и прочее, если настроено в HA.
    notify_enabled: bool = True
    notify_service: str = "persistent_notification.create"
    # Виды событий через запятую. Пусто - виды по умолчанию (сбои и проблемы).
    notify_events: str = ""
    # Тихие часы, например 23:00 и 07:00. Срочное придёт и в них.
    notify_quiet_from: str = ""
    notify_quiet_to: str = ""
    # Часовой пояс для расписаний и тихих часов.
    timezone: str = "UTC"

    # Токен Supervisor читается без префикса: так его называет сам HA.
    supervisor_token: str = Field(default="", validation_alias="SUPERVISOR_TOKEN")

    @property
    def checked_timezone(self) -> str:
        """Часовой пояс, который система действительно знает. Иначе UTC и запись в журнал.

        В Windows базы часовых поясов нет вовсе: её приносит пакет tzdata.
        """
        try:
            ZoneInfo(self.timezone)
        except Exception:
            log.warning("unknown timezone %r, falling back to UTC", self.timezone)
            return "UTC"
        return self.timezone

    @property
    def notification_rules(self) -> NotificationRules:
        kinds = DEFAULT_KINDS
        if self.notify_events.strip():
            names = [name.strip() for name in self.notify_events.split(",") if name.strip()]
            kinds = frozenset(EventKind(name) for name in names)
        return NotificationRules(
            kinds=kinds,
            quiet_from=_parse_time(self.notify_quiet_from),
            quiet_to=_parse_time(self.notify_quiet_to),
            timezone=self.checked_timezone,
        )

    @property
    def ha_websocket_url(self) -> str:
        if self.supervisor_token:
            return SUPERVISOR_WS_URL
        if not self.ha_url:
            raise ValueError("set PLANT_CONTROL_HA_URL or run inside Home Assistant")
        base = self.ha_url.rstrip("/")
        base = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return f"{base}/api/websocket"

    @property
    def ha_access_token(self) -> str:
        token = self.supervisor_token or self.ha_token
        if not token:
            raise ValueError("set PLANT_CONTROL_HA_TOKEN or run inside Home Assistant")
        return token


def _parse_time(value: str) -> time | None:
    """ "23:00" -> time(23, 0). Пустая строка - времени нет."""
    if not value.strip():
        return None
    return time.fromisoformat(value.strip())
