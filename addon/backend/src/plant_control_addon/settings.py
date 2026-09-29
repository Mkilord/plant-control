"""Настройки add-on'а.

Два режима подключения к Home Assistant:
- внутри add-on'а: Supervisor сам кладёт токен в SUPERVISOR_TOKEN,
  а HA доступен по внутреннему адресу supervisor;
- при разработке: адрес HA и долгоживущий токен из .env или переменных окружения.
"""

import logging
from pathlib import Path
from zoneinfo import ZoneInfo

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

    # MQTT: сущности машин в Home Assistant. Включение и брокер настраиваются
    # в интерфейсе. Здесь - брокер для режима "автоматически" при разработке,
    # когда Supervisor его не выдаёт.
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    # Уведомления настраиваются в интерфейсе (шестерёнка) и хранятся в базе.
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
