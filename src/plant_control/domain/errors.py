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
