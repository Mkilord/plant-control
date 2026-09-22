"""Запуск: python -m plant_control_addon"""

import logging

import uvicorn

from plant_control_addon.api.app import create_app
from plant_control_addon.settings import Settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = Settings()
    uvicorn.run(create_app(), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
