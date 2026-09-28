"""Сборка приложения FastAPI."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from plant_control.application.health import HealthService
from plant_control.application.ports import Sleeper
from plant_control.domain.problems import ProblemBoard
from pydantic import BaseModel

from plant_control_addon.api.errors import install_error_handlers
from plant_control_addon.api.ha_routes import HaGateway
from plant_control_addon.api.ha_routes import router as ha_router
from plant_control_addon.api.machines import router as machines_router
from plant_control_addon.api.problems import router as problems_router
from plant_control_addon.controller import Controller, SystemClock
from plant_control_addon.ha.client import HomeAssistantClient
from plant_control_addon.health_source import HaHealthSource
from plant_control_addon.registry import MachineRegistry
from plant_control_addon.settings import Settings
from plant_control_addon.storage import MachineStore

DB_NAME = "plant_control.db"
PACKAGE_STATIC = Path(__file__).resolve().parent.parent / "static"


class Health(BaseModel):
    status: str
    home_assistant: str
    machines: int


def create_app(
    *,
    ha: HaGateway | None = None,
    data_dir: Path | None = None,
    sleeper: Sleeper | None = None,
    watchdog_interval: float = 1.0,
    health_interval: float = 30.0,
) -> FastAPI:
    """ha, data_dir и sleeper подменяют тесты. Без них всё берётся из настроек."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Всё до yield выполняется при старте, после yield - при остановке.
        settings = Settings()
        client: HaGateway
        real_client: HomeAssistantClient | None = None
        if ha is None:
            real_client = HomeAssistantClient(settings.ha_websocket_url, settings.ha_access_token)
            client = real_client
        else:
            client = ha

        registry = MachineRegistry(MachineStore((data_dir or settings.data_dir) / DB_NAME))
        await registry.load()
        clock = SystemClock()
        board = ProblemBoard()
        health = HealthService(registry, board, clock)
        controller = Controller(
            registry,
            client,
            clock=clock,
            sleeper=sleeper,
            health=health,
            health_source=HaHealthSource(client, registry),
        )
        client.add_state_listener(controller.on_state_changed)
        client.add_connect_listener(controller.on_connected)

        app.state.ha = client
        app.state.registry = registry
        app.state.controller = controller

        if real_client is not None:
            await real_client.start()
            await real_client.wait_connected(timeout=10)
        elif client.is_connected:
            await controller.safe_start_all()

        app.state.problems = board
        watchdog = asyncio.create_task(controller.watchdog(watchdog_interval))
        health_task = asyncio.create_task(controller.health_loop(health_interval))
        try:
            yield
        finally:
            for task in (watchdog, health_task):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await controller.shutdown()
            if real_client is not None:
                await real_client.stop()

    app = FastAPI(title="PlantControl", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(ha_router)
    app.include_router(machines_router)
    app.include_router(problems_router)

    @app.get("/api/health", tags=["service"])
    async def health() -> Health:
        client: HaGateway = app.state.ha
        auth_error = getattr(client, "auth_error", None)
        if auth_error:
            ha_status = f"auth failed: {auth_error}"
        else:
            ha_status = "connected" if client.is_connected else "disconnected"
        return Health(
            status="ok", home_assistant=ha_status, machines=len(app.state.registry.entries())
        )

    # Фронт подключается последним: всё, что не /api, отдаётся как статика.
    static_dir = static_dir_from(Settings())
    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


def static_dir_from(settings: Settings) -> Path | None:
    candidate = settings.static_dir or PACKAGE_STATIC
    return candidate if (candidate / "index.html").is_file() else None
