"""Тесты проверки состояния."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from plant_control.application.health import HealthService
from plant_control.domain.machine import WateringMachine
from plant_control.domain.problems import Observation, Problem, ProblemBoard, ProblemKind
from tests.application.builders import collector_machine, simple_machine
from tests.application.fakes import FakeClock

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


class Directory:
    def __init__(self, *machines: WateringMachine) -> None:
        self._machines = list(machines)

    def machines(self) -> Sequence[WateringMachine]:
        return self._machines


def service(*machines: WateringMachine, clock: FakeClock | None = None) -> HealthService:
    return HealthService(Directory(*machines), ProblemBoard(), clock or FakeClock(T0))


def kinds(items: Sequence[Observation] | Sequence[Problem]) -> list[ProblemKind]:
    return [item.kind for item in items]


def test_healthy_machine_has_no_problems() -> None:
    report = service(simple_machine()).check()
    assert report.active == []


def test_unknown_pump_state_is_a_problem() -> None:
    machine = simple_machine()
    machine.pump.mark_unknown()
    report = service(machine).check()
    assert kinds(report.opened) == [ProblemKind.PUMP_STATE_UNKNOWN]
    assert report.active[0].blocking


def test_pump_overrun_is_a_problem() -> None:
    machine = simple_machine()
    machine.pump.mark_started(T0)
    clock = FakeClock(T0 + timedelta(seconds=120))
    report = service(machine, clock=clock).check()
    assert ProblemKind.PUMP_OVERRUN in kinds(report.opened)


def test_unknown_valve_is_a_problem_per_valve() -> None:
    machine = collector_machine()
    assert machine.collector is not None
    machine.collector.mark_unknown("v1")
    report = service(machine).check()
    problems = [p for p in report.active if p.kind is ProblemKind.VALVE_STATE_UNKNOWN]
    assert [p.target for p in problems] == ["v1"]


def test_low_water_and_empty_tank() -> None:
    machine = simple_machine()
    # Бак 2 л, запас 500 мл. Оставляем 600 мл: доступно 100, это меньше 15% бака.
    machine.tank.set_measured_volume(600)
    report = service(machine).check()
    assert kinds(report.opened) == [ProblemKind.TANK_LOW]
    assert not report.active[0].blocking

    machine.tank.set_measured_volume(400)
    report = service(machine).check()
    assert kinds(report.active) == [ProblemKind.TANK_EMPTY]


def test_problem_closes_when_tank_is_refilled() -> None:
    machine = simple_machine()
    machine.tank.set_measured_volume(400)
    health = service(machine)
    health.check()

    machine.tank.fill_full()
    report = health.check()
    assert kinds(report.closed) == [ProblemKind.TANK_EMPTY]
    assert report.active == []


def test_extra_observations_from_infrastructure() -> None:
    machine = simple_machine()
    extra = Observation(machine.id, ProblemKind.HA_DISCONNECTED, details="нет связи")
    report = service(machine).check([extra])
    assert kinds(report.opened) == [ProblemKind.HA_DISCONNECTED]
