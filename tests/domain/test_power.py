"""Тесты группы питания."""

from datetime import UTC, datetime, timedelta

import pytest

from plant_control.domain.errors import InvalidPowerGroupError
from plant_control.domain.power import PowerGroup, StartBlock, solo_group

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def test_single_pump_group_allows_one_watering() -> None:
    group = PowerGroup("psu-1", max_concurrent=1, min_start_gap=timedelta(0))
    assert group.check_can_start(running=0, last_start_at=None, now=T0) is None
    assert group.check_can_start(running=1, last_start_at=None, now=T0) is StartBlock.GROUP_BUSY


def test_group_allows_several_when_configured() -> None:
    group = PowerGroup("psu-1", max_concurrent=3, min_start_gap=timedelta(0))
    assert group.check_can_start(running=2, last_start_at=None, now=T0) is None
    assert group.check_can_start(running=3, last_start_at=None, now=T0) is StartBlock.GROUP_BUSY


def test_gap_between_starts() -> None:
    group = PowerGroup("psu-1", max_concurrent=2, min_start_gap=timedelta(seconds=5))
    assert group.check_can_start(0, T0 - timedelta(seconds=2), T0) is StartBlock.TOO_SOON
    assert group.check_can_start(0, T0 - timedelta(seconds=6), T0) is None


def test_solo_group_is_per_machine() -> None:
    assert solo_group("m-1").id != solo_group("m-2").id
    assert solo_group("m-1").max_concurrent == 1


def test_invalid_group() -> None:
    with pytest.raises(InvalidPowerGroupError):
        PowerGroup("psu-1", max_concurrent=0)
