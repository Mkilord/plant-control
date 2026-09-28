"""API проблем: список, подтверждение, приглушение.

Проблемы не создаются и не закрываются руками: они появляются и исчезают сами
по результатам проверки состояния. Руками можно только сказать "вижу"
и приглушить показ на время.
"""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from plant_control.domain.problems import Problem, ProblemBoard, ProblemKey, ProblemKind
from pydantic import BaseModel, Field

from plant_control_addon.api.machines import get_controller
from plant_control_addon.controller import Controller


def get_board(request: Request) -> ProblemBoard:
    board: ProblemBoard = request.app.state.problems
    return board


Board = Annotated[ProblemBoard, Depends(get_board)]
Control = Annotated[Controller, Depends(get_controller)]


class ProblemOut(BaseModel):
    id: str
    machine_id: str
    kind: str
    target: str
    severity: str
    blocking: bool
    details: str
    opened_at: datetime
    last_seen_at: datetime
    acknowledged: bool
    muted_until: datetime | None


class MuteRequest(BaseModel):
    hours: float = Field(default=24, gt=0, le=24 * 30)


def problem_id(problem: Problem) -> str:
    return f"{problem.machine_id}|{problem.kind.value}|{problem.target}"


def parse_id(value: str) -> ProblemKey:
    try:
        machine_id, kind, target = value.split("|", 2)
        return (machine_id, ProblemKind(kind), target)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown problem {value!r}") from None


def problem_out(problem: Problem) -> ProblemOut:
    return ProblemOut(
        id=problem_id(problem),
        machine_id=problem.machine_id,
        kind=problem.kind.value,
        target=problem.target,
        severity=problem.severity.value,
        blocking=problem.blocking,
        details=problem.details,
        opened_at=problem.opened_at,
        last_seen_at=problem.last_seen_at,
        acknowledged=problem.acknowledged_at is not None,
        muted_until=problem.muted_until,
    )


router = APIRouter(prefix="/api/problems", tags=["problems"])


@router.get("")
async def list_problems(board: Board, machine_id: str | None = None) -> list[ProblemOut]:
    problems = board.for_machine(machine_id) if machine_id else board.all()
    return [problem_out(problem) for problem in problems]


@router.post("/check")
async def check_now(control: Control) -> list[ProblemOut]:
    """Проверить состояние прямо сейчас, не дожидаясь фоновой проверки."""
    report = await control.check_health()
    problems = report.active if report else []
    return [problem_out(problem) for problem in problems]


@router.post("/{problem_id}/ack")
async def acknowledge(problem_id: str, board: Board, control: Control) -> ProblemOut:
    problem = board.acknowledge(parse_id(problem_id), control.now())
    if problem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown problem {problem_id!r}")
    return problem_out(problem)


@router.post("/{problem_id}/mute")
async def mute(problem_id: str, body: MuteRequest, board: Board, control: Control) -> ProblemOut:
    until = control.now() + timedelta(hours=body.hours)
    problem = board.mute(parse_id(problem_id), until)
    if problem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown problem {problem_id!r}")
    return problem_out(problem)


@router.post("/{problem_id}/unmute")
async def unmute(problem_id: str, board: Board) -> ProblemOut:
    problem = board.unmute(parse_id(problem_id))
    if problem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown problem {problem_id!r}")
    return problem_out(problem)
