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


# --- Поливальная машина ---


class MachineError(Exception):
    pass


class InvalidMachineError(MachineError):
    pass


class UnknownRouteError(MachineError):
    pass


class MachineBusyError(MachineError):
    pass
