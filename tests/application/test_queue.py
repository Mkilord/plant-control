"""Тесты очереди поливов."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from plant_control.application.queue import (
    RequestSource,
    RequestState,
    WateringQueue,
    WateringRequest,
    groups_by_machine,
)
from plant_control.domain.errors import UnknownRequestError
from plant_control.domain.power import PowerGroup
from tests.application.fakes import FakeClock

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def state(request: WateringRequest) -> RequestState:
    """Состояние заявки. Через функцию, иначе проверка типов считает его неизменным."""
    return request.state


class FakeRunner:
    """Поливает не по-настоящему: держит событие, пока тест не отпустит."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.finished: list[str] = []
        self.gates: dict[str, asyncio.Event] = {}
        self.fail: set[str] = set()

    def gate(self, machine_id: str) -> asyncio.Event:
        return self.gates.setdefault(machine_id, asyncio.Event())

    async def water(self, machine_id: str, route_id: str, dose_ml: float) -> None:
        self.started.append(machine_id)
        await self.gate(machine_id).wait()
        if machine_id in self.fail:
            raise RuntimeError("relay is dead")
        self.finished.append(machine_id)


async def settle() -> None:
    """Дать задачам очереди провернуться."""
    for _ in range(5):
        await asyncio.sleep(0)


class Rig:
    def __init__(self, group_of: object = None) -> None:
        self.clock = FakeClock(T0)
        self.runner = FakeRunner()
        self.queue = WateringQueue(self.runner, self.clock, group_of)  # type: ignore[arg-type]

    async def dispatch(self) -> None:
        self.queue.dispatch()
        await settle()

    async def release(self, machine_id: str) -> None:
        self.runner.gate(machine_id).set()
        await settle()


# --- Одна машина ---


async def test_request_runs_and_finishes() -> None:
    rig = Rig()
    request = rig.queue.submit("m-1", "main", 100)
    await rig.dispatch()
    assert state(request) is RequestState.RUNNING

    await rig.release("m-1")
    assert state(request) is RequestState.DONE
    assert rig.runner.finished == ["m-1"]


async def test_one_watering_per_machine() -> None:
    rig = Rig()
    first = rig.queue.submit("m-1", "main", 100)
    second = rig.queue.submit("m-1", "main", 50)
    await rig.dispatch()

    assert state(first) is RequestState.RUNNING
    assert state(second) is RequestState.QUEUED
    assert rig.queue.position(second.id) == 1

    # Отпускаем первый полив: очередь сама берётся за второй.
    await rig.release("m-1")
    await rig.dispatch()
    assert state(first) is RequestState.DONE
    assert rig.runner.started == ["m-1", "m-1"]


async def test_failed_watering_keeps_error() -> None:
    rig = Rig()
    rig.runner.fail.add("m-1")
    request = rig.queue.submit("m-1", "main", 100)
    await rig.dispatch()
    await rig.release("m-1")

    assert state(request) is RequestState.FAILED
    assert request.error is not None and "relay is dead" in request.error


# --- Группа питания ---


def one_psu(*machines: str) -> object:
    group = PowerGroup("psu-1", max_concurrent=1, min_start_gap=timedelta(0))
    return groups_by_machine((machine, group) for machine in machines)


async def test_machines_on_one_power_supply_water_one_by_one() -> None:
    rig = Rig(one_psu("m-1", "m-2"))
    first = rig.queue.submit("m-1", "main", 100)
    second = rig.queue.submit("m-2", "main", 100)
    await rig.dispatch()

    assert state(first) is RequestState.RUNNING
    assert state(second) is RequestState.QUEUED

    # Первая машина закончила: очередь берётся за вторую.
    await rig.release("m-1")
    await rig.dispatch()
    assert state(first) is RequestState.DONE
    assert state(second) is RequestState.RUNNING


async def test_machines_in_different_groups_water_together() -> None:
    rig = Rig()
    first = rig.queue.submit("m-1", "main", 100)
    second = rig.queue.submit("m-2", "main", 100)
    await rig.dispatch()
    assert state(first) is RequestState.RUNNING
    assert state(second) is RequestState.RUNNING


async def test_group_limit_of_two() -> None:
    group = PowerGroup("psu-1", max_concurrent=2, min_start_gap=timedelta(0))
    rig = Rig(groups_by_machine((m, group) for m in ("m-1", "m-2", "m-3")))
    requests = [rig.queue.submit(m, "main", 100) for m in ("m-1", "m-2", "m-3")]
    await rig.dispatch()
    states = [state(r) for r in requests]
    assert states.count(RequestState.RUNNING) == 2
    assert states.count(RequestState.QUEUED) == 1


async def test_gap_between_starts_delays_second_machine() -> None:
    group = PowerGroup("psu-1", max_concurrent=2, min_start_gap=timedelta(seconds=10))
    rig = Rig(groups_by_machine((m, group) for m in ("m-1", "m-2")))
    first = rig.queue.submit("m-1", "main", 100)
    second = rig.queue.submit("m-2", "main", 100)
    await rig.dispatch()
    assert state(first) is RequestState.RUNNING
    assert state(second) is RequestState.QUEUED

    rig.clock.current = T0 + timedelta(seconds=11)
    await rig.dispatch()
    assert state(second) is RequestState.RUNNING


# --- Порядок, отмена, срок ожидания ---


async def test_manual_request_goes_before_schedule() -> None:
    rig = Rig(one_psu("m-1", "m-2", "m-3"))
    rig.queue.submit("m-1", "main", 100)
    from_schedule = rig.queue.submit("m-2", "main", 100, RequestSource.SCHEDULE)
    manual = rig.queue.submit("m-3", "main", 100, RequestSource.MANUAL)
    await rig.dispatch()

    assert rig.queue.position(manual.id) == 1
    assert rig.queue.position(from_schedule.id) == 2


async def test_cancel_queued_request() -> None:
    rig = Rig(one_psu("m-1", "m-2"))
    rig.queue.submit("m-1", "main", 100)
    waiting = rig.queue.submit("m-2", "main", 100)
    await rig.dispatch()

    rig.queue.cancel(waiting.id)
    assert state(waiting) is RequestState.CANCELLED
    assert rig.queue.queued() == []


async def test_cancel_running_request() -> None:
    rig = Rig()
    request = rig.queue.submit("m-1", "main", 100)
    await rig.dispatch()
    rig.queue.cancel(request.id)
    await settle()
    assert state(request) is RequestState.CANCELLED
    assert rig.runner.finished == []


async def test_cancel_machine_clears_queue_and_run() -> None:
    rig = Rig()
    running = rig.queue.submit("m-1", "main", 100)
    await rig.dispatch()
    waiting = rig.queue.submit("m-1", "main", 50)

    rig.queue.cancel_machine("m-1")
    await settle()
    assert state(running) is RequestState.CANCELLED
    assert state(waiting) is RequestState.CANCELLED


async def test_cancel_unknown_request() -> None:
    with pytest.raises(UnknownRequestError):
        Rig().queue.cancel("nope")


async def test_schedule_request_expires_if_it_waits_too_long() -> None:
    rig = Rig(one_psu("m-1", "m-2"))
    rig.queue.submit("m-1", "main", 100)
    waiting = rig.queue.submit(
        "m-2", "main", 100, RequestSource.SCHEDULE, max_wait=timedelta(minutes=30)
    )
    await rig.dispatch()

    rig.clock.current = T0 + timedelta(minutes=31)
    await rig.dispatch()
    assert state(waiting) is RequestState.EXPIRED


async def test_history_keeps_finished_requests() -> None:
    rig = Rig()
    request = rig.queue.submit("m-1", "main", 100)
    await rig.dispatch()
    await rig.release("m-1")
    assert [r.id for r in rig.queue.history()] == [request.id]
    assert rig.queue.find(request.id).state is RequestState.DONE


async def test_run_loop_dispatches_by_itself() -> None:
    rig = Rig()
    task = asyncio.create_task(rig.queue.run())
    try:
        request = rig.queue.submit("m-1", "main", 100)
        await settle()
        assert state(request) is RequestState.RUNNING
        await rig.release("m-1")
        assert state(request) is RequestState.DONE
    finally:
        task.cancel()


async def test_skipped_watering_goes_to_history_only() -> None:
    finished: list[WateringRequest] = []
    rig = Rig()
    rig.queue._on_finished = finished.append
    request = rig.queue.record_skipped("m-1", "main", 100, "recently_watered")

    assert request.state is RequestState.SKIPPED
    assert request.error == "recently_watered"
    assert rig.queue.queued() == []
    assert rig.queue.history() == [request]
    assert finished == [request]


def test_history_from_last_run_is_kept_newest_first() -> None:
    old = WateringRequest("a", 1, "m-1", "main", 50, RequestSource.MANUAL, T0)
    old.finished_at = T0
    new = WateringRequest("b", 2, "m-1", "main", 50, RequestSource.MANUAL, T0)
    new.finished_at = T0 + timedelta(hours=1)

    queue = WateringQueue(Rig().queue._runner, FakeClock(T0), history=[old, new])

    assert [r.id for r in queue.history()] == ["b", "a"]
