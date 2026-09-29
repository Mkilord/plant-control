"""Перевод доменных ошибок и ошибок инфраструктуры в HTTP-ответы.

Как @ControllerAdvice в Spring: один обработчик на базовый класс ошибок,
а код ответа выбирается по первому подходящему классу из списка.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from plant_control.application.ports import PumpControlError, ValveControlError
from plant_control.domain.errors import (
    AnotherValveOpenError,
    CollectorError,
    CollectorStateUnknownError,
    HydraulicsError,
    MachineBusyError,
    MachineError,
    NotEnoughWaterError,
    PumpAlreadyRunningError,
    PumpCoolingDownError,
    PumpError,
    PumpStateUnknownError,
    TankError,
    TankOverflowError,
    UnknownRequestError,
    UnknownRouteError,
    UnknownValveError,
    ValveAlreadyOpenError,
    WateringBlockedError,
)

from plant_control_addon.ha.client import HomeAssistantError
from plant_control_addon.registry import UnknownMachineError

# Порядок важен: сначала конкретные классы, потом общие.
STATUS_BY_ERROR: list[tuple[type[Exception], int]] = [
    (UnknownMachineError, status.HTTP_404_NOT_FOUND),
    (UnknownRouteError, status.HTTP_404_NOT_FOUND),
    (UnknownValveError, status.HTTP_404_NOT_FOUND),
    (UnknownRequestError, status.HTTP_404_NOT_FOUND),
    # Правило нарушено из-за текущего состояния: позже может получиться.
    (MachineBusyError, status.HTTP_409_CONFLICT),
    (WateringBlockedError, status.HTTP_409_CONFLICT),
    (PumpAlreadyRunningError, status.HTTP_409_CONFLICT),
    (PumpCoolingDownError, status.HTTP_409_CONFLICT),
    (PumpStateUnknownError, status.HTTP_409_CONFLICT),
    (ValveAlreadyOpenError, status.HTTP_409_CONFLICT),
    (AnotherValveOpenError, status.HTTP_409_CONFLICT),
    (CollectorStateUnknownError, status.HTTP_409_CONFLICT),
    (NotEnoughWaterError, status.HTTP_409_CONFLICT),
    (TankOverflowError, status.HTTP_409_CONFLICT),
    # Реле или HA недоступны.
    (PumpControlError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (ValveControlError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (HomeAssistantError, status.HTTP_503_SERVICE_UNAVAILABLE),
    # Остальное: запрос или конфигурация невозможны в принципе.
    (Exception, status.HTTP_422_UNPROCESSABLE_CONTENT),
]

HANDLED: tuple[type[Exception], ...] = (
    UnknownMachineError,
    UnknownRequestError,
    PumpError,
    CollectorError,
    TankError,
    HydraulicsError,
    MachineError,
    PumpControlError,
    ValveControlError,
    HomeAssistantError,
)


async def _handle(request: Request, error: Exception) -> JSONResponse:
    code = next(code for kind, code in STATUS_BY_ERROR if isinstance(error, kind))
    content: dict[str, Any] = {"error": type(error).__name__, "detail": str(error)}
    if isinstance(error, WateringBlockedError):
        # Что именно мешает: интерфейс покажет это своими словами.
        content["problems"] = [
            {"kind": p.kind.value, "target": p.target, "details": p.details} for p in error.problems
        ]
    return JSONResponse(status_code=code, content=content)


def install_error_handlers(app: FastAPI) -> None:
    for kind in HANDLED:
        app.add_exception_handler(kind, _handle)
