"""Группа питания: сколько насосов можно держать включёнными одновременно.

Несколько машин часто питаются от одного блока. Если запустить их разом,
напряжение просядет, расход упадёт, и расчёт полива станет врать. Группа задаёт
предел одновременных поливов и паузу между стартами.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from plant_control.domain.errors import InvalidPowerGroupError


class StartBlock(Enum):
    """Почему сейчас нельзя начать полив в этой группе."""

    GROUP_BUSY = "group_busy"  # занято максимальное число поливов
    TOO_SOON = "too_soon"  # не выдержана пауза между стартами


@dataclass(frozen=True, slots=True)
class PowerGroup:
    id: str
    name: str = ""
    # Сколько поливов в группе может идти одновременно. 1 - строго по очереди.
    max_concurrent: int = 1
    # Минимальная пауза между включениями насосов, чтобы не было броска тока.
    min_start_gap: timedelta = timedelta(seconds=2)
    # Сколько заявка может ждать места в группе. None - сколько угодно.
    max_wait: timedelta | None = None

    def __post_init__(self) -> None:
        if self.max_concurrent < 1:
            raise InvalidPowerGroupError(f"max_concurrent must be >= 1, got {self.max_concurrent}")
        if self.min_start_gap < timedelta(0):
            raise InvalidPowerGroupError("min_start_gap must not be negative")
        if self.max_wait is not None and self.max_wait <= timedelta(0):
            raise InvalidPowerGroupError("max_wait must be positive")

    def check_can_start(
        self, running: int, last_start_at: datetime | None, now: datetime
    ) -> StartBlock | None:
        """None - можно начинать. Иначе причина, по которой надо подождать."""
        if running >= self.max_concurrent:
            return StartBlock.GROUP_BUSY
        if last_start_at is not None and now - last_start_at < self.min_start_gap:
            return StartBlock.TOO_SOON
        return None

    def waited_too_long(self, requested_at: datetime, now: datetime) -> bool:
        """Заявка ждёт места в группе дольше, чем разрешает политика группы."""
        return self.max_wait is not None and now - requested_at > self.max_wait


# Группа по умолчанию для машины, которой группу не задали: сама с собой, по одному поливу.
def solo_group(machine_id: str) -> PowerGroup:
    # Пауза между стартами тут не нужна: она про общий блок питания, а машина одна.
    return PowerGroup(
        id=f"solo:{machine_id}",
        name=machine_id,
        max_concurrent=1,
        min_start_gap=timedelta(0),
    )
