from collections.abc import Sequence
from typing import Any


# Базовая ошибка домена насоса. Все остальные наследуются от неё,
# чтобы снаружи можно было ловить одним except PumpError.
# В Python нет checked exceptions, throws писать не нужно.
class PumpError(Exception):
    pass


class PumpAlreadyRunningError(PumpError):
    pass


class PumpCoolingDownError(PumpError):
    pass


class PumpRuntimeExceededError(PumpError):
    pass


class PumpStateUnknownError(PumpError):
    pass


class InvalidPumpPassportError(PumpError):
    pass


# --- Коллектор ---


class CollectorError(Exception):
    pass


class InvalidCollectorError(CollectorError):
    pass


class UnknownValveError(CollectorError):
    pass


class ValveAlreadyOpenError(CollectorError):
    pass


class AnotherValveOpenError(CollectorError):
    pass


class CollectorStateUnknownError(CollectorError):
    pass


# --- Бак ---


class TankError(Exception):
    pass


class InvalidTankError(TankError):
    pass


class NotEnoughWaterError(TankError):
    pass


class TankOverflowError(TankError):
    pass


# --- Гидравлика и расчёт полива ---


class HydraulicsError(Exception):
    pass


class InvalidFlowCurveError(HydraulicsError):
    pass


class InvalidConnectionError(HydraulicsError):
    pass


class InvalidWateringRequestError(HydraulicsError):
    pass


class PumpCannotDeliverError(HydraulicsError):
    pass


class DoseTooSmallError(InvalidWateringRequestError):
    """Доза меньше того, что само дотекает после выключения насоса."""


# --- Калибровка ---


class CalibrationError(HydraulicsError):
    """Данные замера не дают посчитать расход: мало точек, время назад и так далее."""


class RouteNotCalibratedError(HydraulicsError):
    """Маршрут работает по калибровке, а калибровки ни у него, ни у базового нет."""


# --- Поливальная машина ---


class MachineError(Exception):
    pass


class InvalidMachineError(MachineError):
    pass


class UnknownRouteError(MachineError):
    pass


class MachineBusyError(MachineError):
    pass


class WateringBlockedError(MachineError):
    """Полив невозможен, пока не решатся проблемы. problems - что мешает."""

    def __init__(self, message: str, problems: Sequence[Any] = ()) -> None:
        super().__init__(message)
        self.problems = list(problems)


# --- Расписание ---


class ScheduleError(Exception):
    pass


class InvalidScheduleError(ScheduleError):
    pass


# --- Питание и очередь ---


class PowerError(Exception):
    pass


class InvalidPowerGroupError(PowerError):
    pass


class UnknownRequestError(PowerError):
    pass
