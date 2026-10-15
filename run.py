"""Запуск внутри Home Assistant.

Supervisor кладёт настройки add-on'а в /data/options.json. Здесь они
превращаются в переменные окружения, которые читает Settings, и поднимается
приложение. Отдельный файл нужен, чтобы сам пакет ничего не знал про Supervisor.
"""

import json
import logging
import os
from pathlib import Path

OPTIONS = Path("/data/options.json")
# Ключ настройки -> переменная окружения. Значения, которых нет, пропускаются.
ENV_BY_OPTION = {
    "timezone": "PLANT_CONTROL_TIMEZONE",
}


def load_options() -> str:
    """Переносит настройки в окружение и возвращает уровень логов."""
    if not OPTIONS.is_file():
        return os.environ.get("LOG_LEVEL", "info")
    options = json.loads(OPTIONS.read_text(encoding="utf-8"))
    for key, name in ENV_BY_OPTION.items():
        value = options.get(key)
        if value is None or value == "":
            continue
        os.environ[name] = str(value).lower() if isinstance(value, bool) else str(value)
    # Пояс не задан - берётся пояс Home Assistant: Supervisor передаёт его в TZ.
    if "PLANT_CONTROL_TIMEZONE" not in os.environ and os.environ.get("TZ"):
        os.environ["PLANT_CONTROL_TIMEZONE"] = os.environ["TZ"]
    level: str = options.get("log_level", "info")
    return level


def main() -> None:
    level = load_options()
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    import uvicorn
    from plant_control_addon.api.app import create_app
    from plant_control_addon.settings import Settings

    settings = Settings()
    uvicorn.run(create_app(), host="0.0.0.0", port=settings.port, log_level=level)


if __name__ == "__main__":
    main()
