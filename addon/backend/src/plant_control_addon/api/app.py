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
from plant_control.application.queue import HISTORY_LIMIT
from plant_control.application.scheduler import SchedulerService
from plant_control.domain.problems import ProblemBoard
from pydantic import BaseModel
from starlette.responses import Response
from starlette.types import Scope

from plant_control_addon.api.calibration_routes import router as calibration_router
from plant_control_addon.api.catalog_routes import router as catalog_router
from plant_control_addon.api.errors import install_error_handlers
from plant_control_addon.api.ha_routes import HaGateway
from plant_control_addon.api.ha_routes import router as ha_router
from plant_control_addon.api.journal_routes import router as journal_router
from plant_control_addon.api.machines import router as machines_router
from plant_control_addon.api.mqtt_routes import router as mqtt_router
from plant_control_addon.api.notification_routes import router as notifications_router
from plant_control_addon.api.problems import router as problems_router
from plant_control_addon.api.queue_routes import router as queue_router
from plant_control_addon.api.queue_routes import schedules_router
from plant_control_addon.api.transfer_routes import router as transfer_router
from plant_control_addon.calibration import CalibrationManager, Hooks
from plant_control_addon.controller import Controller, SystemClock
from plant_control_addon.ha.client import HomeAssistantClient
from plant_control_addon.ha.supervisor import panel_path
from plant_control_addon.health_source import HaHealthSource
from plant_control_addon.journals import Journals
from plant_control_addon.mqtt.bridge import MqttBridge
from plant_control_addon.mqtt.settings import MqttManager
from plant_control_addon.mqtt.transport import BrokerConfig, resolve_broker, session_factory
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
            # Журнал поливов живёт в базе: после перезапуска история на месте.
            journal=store,
            history=await store.load_waterings(HISTORY_LIMIT),
        )
        calibration = CalibrationManager(
            registry,
            store,
            Hooks(
                actuation=controller.actuation,
                ensure_can_water=controller.ensure_can_calibrate,
                is_watering=controller.is_watering,
                now=clock.now,
                sleep=controller.sleep_s,
            ),
        )
        await calibration.load()
        controller.calibration = calibration
        journals = Journals(store, registry, controller.queue, clock.now)
        await journals.load()
        controller.problem_journal = journals.record
        app.state.journals = journals
        app.state.calibration = calibration
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
            asyncio.create_task(journals.prune_loop()),
        ]

        # Мост в HA через MQTT: брокер и включение настраиваются в интерфейсе.
        def make_bridge(broker: BrokerConfig, prefix: str) -> MqttBridge:
            return MqttBridge(
                session_factory(broker), registry, controller, board, discovery_prefix=prefix
            )

        mqtt_manager = MqttManager(
            store, lambda: resolve_broker(settings), make_bridge, allowed=mqtt
        )
        await mqtt_manager.load()
        app.state.mqtt = mqtt_manager

        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await mqtt_manager.stop()
            await controller.shutdown()
            if real_client is not None:
                await real_client.stop()

    app = FastAPI(title="PlantControl", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(calibration_router)
    app.include_router(catalog_router)
    app.include_router(ha_router)
    app.include_router(journal_router)
    app.include_router(machines_router)
    app.include_router(mqtt_router)
    app.include_router(notifications_router)
    app.include_router(problems_router)
    app.include_router(queue_router)
    app.include_router(schedules_router)
    app.include_router(transfer_router)

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
        app.mount("/", FrontendFiles(directory=static_dir, html=True), name="frontend")

    return app


class FrontendFiles(StaticFiles):
    """Статика интерфейса с правильным кэшированием.

    index.html браузер должен проверять каждый раз: в нём ссылки на скрипты текущей
    версии. Иначе после обновления add-on'а браузер или приложение HA показывают
    старый интерфейс. Файлы из assets/ с хэшем в имени не меняются никогда,
    их можно хранить сколько угодно.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


def static_dir_from(settings: Settings) -> Path | None:
    candidate = settings.static_dir or PACKAGE_STATIC
    return candidate if (candidate / "index.html").is_file() else None
