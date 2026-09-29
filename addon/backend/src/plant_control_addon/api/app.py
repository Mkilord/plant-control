"""Сборка приложения FastAPI."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from plant_control.application.health import HealthService
from plant_control.application.notifications import NotificationService
from plant_control.application.ports import Sleeper
from plant_control.application.scheduler import SchedulerService
from plant_control.domain.problems import ProblemBoard
from pydantic import BaseModel

from plant_control_addon.api.errors import install_error_handlers
from plant_control_addon.api.ha_routes import HaGateway
from plant_control_addon.api.ha_routes import router as ha_router
from plant_control_addon.api.machines import router as machines_router
from plant_control_addon.api.notification_routes import router as notifications_router
from plant_control_addon.api.problems import router as problems_router
from plant_control_addon.api.queue_routes import router as queue_router
from plant_control_addon.api.queue_routes import schedules_router
from plant_control_addon.controller import Controller, SystemClock
from plant_control_addon.ha.client import HomeAssistantClient
from plant_control_addon.ha.supervisor import panel_path
from plant_control_addon.health_source import HaHealthSource
from plant_control_addon.mqtt.bridge import MqttBridge
from plant_control_addon.mqtt.transport import resolve_broker, session_factory
from plant_control_addon.notification_settings import NotificationSettingsManager
from plant_control_addon.notifications import HaEventSink, PushNotifier
from plant_control_addon.registry import MachineRegistry
from plant_control_addon.settings import Settings
from plant_control_addon.storage import MachineStore

log = logging.getLogger(__name__)

DB_NAME = "plant_control.db"
PACKAGE_STATIC = Path(__file__).resolve().parent.parent / "static"


class Health(BaseModel):
    status: str
    home_assistant: str
    machines: int


def create_app(
    *,
    ha: HaGateway | None = None,
    settings: Settings | None = None,
    data_dir: Path | None = None,
    sleeper: Sleeper | None = None,
    watchdog_interval: float = 1.0,
    health_interval: float = 30.0,
    schedule_interval: float = 30.0,
    queue_tick: float = 0.1,
    mqtt: bool = True,
) -> FastAPI:
    """ha, settings, data_dir и sleeper подменяют тесты. Без них всё берётся из настроек."""

    # Имя параметра занято внутри lifespan, поэтому запоминаем отдельно.
    given_settings = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Всё до yield выполняется при старте, после yield - при остановке.
        settings = given_settings or Settings()
        client: HaGateway
        real_client: HomeAssistantClient | None = None
        if ha is None:
            real_client = HomeAssistantClient(settings.ha_websocket_url, settings.ha_access_token)
            client = real_client
        else:
            client = ha

        store = MachineStore((data_dir or settings.data_dir) / DB_NAME)
        registry = MachineRegistry(store, settings.checked_timezone)
        await registry.load()
        clock = SystemClock()
        board = ProblemBoard()
        health = HealthService(registry, board, clock)
        # Пуши на телефоны и события на шину HA: и то и другое через один сервис.
        # Настройки пушей правятся в интерфейсе и применяются на ходу.
        push = PushNotifier(client, timezone=settings.checked_timezone)
        notifications = NotificationService(clock, sinks=[HaEventSink(client)])
        notification_settings = NotificationSettingsManager(
            store,
            notifications,
            push,
            timezone=settings.checked_timezone,
            panel_url=await panel_path(settings.supervisor_token),
        )
        await notification_settings.load()
        controller = Controller(
            registry,
            client,
            clock=clock,
            sleeper=sleeper,
            health=health,
            health_source=HaHealthSource(client, registry),
            notifications=notifications,
            queue_tick=queue_tick,
        )
        scheduler = SchedulerService(
            registry,
            controller.queue,
            clock,
            notifications=notifications,
            persist=lambda schedule: registry.save_schedules(schedule.machine_id),
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
        app.state.notifications = notifications
        app.state.push = push
        app.state.notification_settings = notification_settings
        app.state.scheduler = scheduler
        tasks = [
            asyncio.create_task(controller.watchdog(watchdog_interval)),
            asyncio.create_task(controller.health_loop(health_interval)),
            asyncio.create_task(controller.queue.run()),
            asyncio.create_task(scheduler.run(schedule_interval)),
        ]

        # Мост в HA поднимается только если брокер вообще есть.
        bridge: MqttBridge | None = None
        if mqtt and settings.mqtt_enabled:
            broker = await resolve_broker(settings)
            if broker is None:
                log.info("mqtt is off: no broker configured")
            else:
                log.info("mqtt broker %s:%s", broker.host, broker.port)
                bridge = MqttBridge(
                    session_factory(broker),
                    registry,
                    controller,
                    board,
                    discovery_prefix=settings.mqtt_discovery_prefix,
                )
                tasks.append(asyncio.create_task(bridge.run()))
        app.state.mqtt = bridge

        try:
            yield
        finally:
            for task in tasks:
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
    app.include_router(notifications_router)
    app.include_router(problems_router)
    app.include_router(queue_router)
    app.include_router(schedules_router)

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
    static_dir = static_dir_from(given_settings or Settings())
    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


def static_dir_from(settings: Settings) -> Path | None:
    candidate = settings.static_dir or PACKAGE_STATIC
    return candidate if (candidate / "index.html").is_file() else None
