"""Servicio transaccional para el ciclo de vida de profiling.

No hace commit: router, webhook o worker controlan la frontera de la transaccion.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.application.hiring_process.progress import sync_process_status, sync_process_status_sync
from src.domain.candidate.state_machine import CandidateStateMachine
from src.domain.profiling.state_machine import (
    TERMINAL_PROFILING_RUN_STATUSES,
    ProfilingRunStateMachine,
)
from src.infrastructure.db.models import (
    CandidateStatus,
    ProcessCandidate,
    ProfilingRun,
    ProfilingRunStatus,
)


def _candidate_transition(pc: ProcessCandidate, target: CandidateStatus) -> None:
    current = CandidateStatus(pc.status)
    if current == target or current in {
        CandidateStatus.DISCARDED,
        CandidateStatus.PROFILING_COMPLETED,
    }:
        return
    pc.status = CandidateStateMachine.transition(current, target)


def _align_candidate(pc: ProcessCandidate, target: ProfilingRunStatus) -> None:
    if target == ProfilingRunStatus.PENDING:
        return
    if target == ProfilingRunStatus.QUEUED:
        _candidate_transition(pc, CandidateStatus.PROFILING_QUEUED)
        return
    if target in {ProfilingRunStatus.CALLING, ProfilingRunStatus.ANSWERED}:
        _candidate_transition(pc, CandidateStatus.PROFILING_CALLING)
        return
    if target == ProfilingRunStatus.RETRY_PENDING:
        if pc.status == CandidateStatus.PROFILING_CALLING.value:
            _candidate_transition(pc, CandidateStatus.PROFILING_FAILED)
        if pc.status == CandidateStatus.PROFILING_FAILED.value:
            _candidate_transition(pc, CandidateStatus.PROFILING_QUEUED)
        return
    if target == ProfilingRunStatus.COMPLETED:
        _candidate_transition(pc, CandidateStatus.PROFILING_COMPLETED)
        return
    if target == ProfilingRunStatus.CANCELLED:
        if pc.status == CandidateStatus.PROFILING_QUEUED.value:
            _candidate_transition(pc, CandidateStatus.SELECTED_FOR_PROFILING)
        return
    if target in TERMINAL_PROFILING_RUN_STATUSES:
        if pc.status == CandidateStatus.SELECTED_FOR_PROFILING.value:
            _candidate_transition(pc, CandidateStatus.PROFILING_QUEUED)
        _candidate_transition(pc, CandidateStatus.PROFILING_FAILED)


def apply_profiling_transition(
    run: ProfilingRun,
    pc: ProcessCandidate,
    target: ProfilingRunStatus,
    *,
    now: datetime | None = None,
    detail: str | None = None,
) -> None:
    """Valida y aplica una transicion tecnica y su reflejo de negocio."""

    now = now or datetime.now(UTC)
    run.status = ProfilingRunStateMachine.transition(ProfilingRunStatus(run.status), target)
    if target == ProfilingRunStatus.CALLING:
        run.started_at = run.started_at or now
    if target in TERMINAL_PROFILING_RUN_STATUSES:
        run.completed_at = run.completed_at or now
    if detail:
        run.twilio_status_detail = detail[:30]
    _align_candidate(pc, target)


async def transition_profiling_async(
    db: AsyncSession,
    run: ProfilingRun,
    pc: ProcessCandidate,
    target: ProfilingRunStatus,
    *,
    now: datetime | None = None,
    detail: str | None = None,
) -> None:
    apply_profiling_transition(run, pc, target, now=now, detail=detail)
    await sync_process_status(db, pc.process_id)


def transition_profiling_sync(
    db: Session,
    run: ProfilingRun,
    pc: ProcessCandidate,
    target: ProfilingRunStatus,
    *,
    now: datetime | None = None,
    detail: str | None = None,
) -> None:
    apply_profiling_transition(run, pc, target, now=now, detail=detail)
    sync_process_status_sync(db, pc.process_id)
