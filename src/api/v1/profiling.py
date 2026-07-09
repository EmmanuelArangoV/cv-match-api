import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import RequireRecruiter, get_current_user
from src.domain.candidate.state_machine import CandidateStateMachine
from src.domain.hiring_process.rules import HiringProcessRules
from src.domain.shared.exceptions import NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    CandidateStatus,
    HiringProcess,
    ProcessCandidate,
    ProcessStatus,
    ProfilingRun,
    User,
    UserRole,
)
from src.infrastructure.db.repositories.candidate_repository import CandidateRepository

router = APIRouter(prefix="/processes", tags=["Profiling"])
global_router = APIRouter(prefix="/profiling", tags=["Profiling"])


class TriggerProfilingRequest(BaseModel):
    process_candidate_ids: list[uuid.UUID]


def _candidate_name(run: ProfilingRun) -> str:
    candidate = run.process_candidate.candidate
    return f"{candidate.name} {candidate.last_name}"


def _serialize_run(run: ProfilingRun, candidate_name: str) -> dict:
    return {
        "id": str(run.id),
        "process_candidate_id": str(run.process_candidate_id),
        "candidate_id": str(run.process_candidate.candidate_id),
        "candidate_name": candidate_name,
        "question_set_id": str(run.question_set_id),
        "status": run.status,
        "call_attempts": run.call_attempts,
        "advancement_probability": run.advancement_probability,
        "advancement_explanation": run.advancement_explanation,
        "transcription_url": run.transcription_url,
        "transcript_summary": run.transcript_summary,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


@router.post("/{process_id}/profiling/trigger")
async def trigger_profiling(
    process_id: uuid.UUID,
    body: TriggerProfilingRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dispara profiling manual (RB-004) para los candidatos MATCHED seleccionados."""
    from src.infrastructure.workers.tasks.profiling import start_profiling_call

    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    HiringProcessRules.require_active_process(ProcessStatus(process.status))
    HiringProcessRules.require_manual_candidate_selection(body.process_candidate_ids)
    HiringProcessRules.require_question_set_for_profiling(process.question_set_id)

    repo = CandidateRepository(db)
    queued: list[ProcessCandidate] = []
    skipped: list[dict] = []

    for pc_id in body.process_candidate_ids:
        pc = await repo.find_process_candidate_by_id(pc_id)
        if not pc or pc.process_id != process_id:
            skipped.append({
                "process_candidate_id": str(pc_id),
                "reason": "No encontrado en este proceso",
            })
            continue
        if pc.status != CandidateStatus.MATCHED.value:
            skipped.append({
                "process_candidate_id": str(pc_id),
                "reason": f"Estado actual '{pc.status}' no es elegible (se requiere MATCHED)",
            })
            continue

        pc.status = CandidateStateMachine.transition(
            CandidateStatus(pc.status), CandidateStatus.SELECTED_FOR_PROFILING
        ).value
        pc.status = CandidateStateMachine.transition(
            CandidateStatus(pc.status), CandidateStatus.PROFILING_QUEUED
        ).value
        queued.append(pc)

    await db.commit()

    tasks = []
    for pc in queued:
        task = start_profiling_call.delay(str(pc.id))
        tasks.append({"process_candidate_id": str(pc.id), "task_id": task.id})

    return {
        "process_id": str(process_id),
        "queued": len(tasks),
        "tasks": tasks,
        "skipped": skipped,
    }


@router.get("/{process_id}/profiling/runs")
async def list_profiling_runs(
    process_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(ProfilingRun)
        .join(ProcessCandidate, ProfilingRun.process_candidate_id == ProcessCandidate.id)
        .where(ProcessCandidate.process_id == process_id)
        .options(
            selectinload(ProfilingRun.process_candidate).selectinload(ProcessCandidate.candidate)
        )
        .order_by(ProfilingRun.created_at.desc())
    )
    runs = list(result.scalars().all())

    return {
        "total": len(runs),
        "profiling_runs": [
            _serialize_run(run, _candidate_name(run))
            for run in runs
        ],
    }


@global_router.get("/runs")
async def list_all_profiling_runs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Listado global de ProfilingRun para la vista /profiling (todas las prospecciones activas)."""
    query = (
        select(ProfilingRun)
        .join(ProcessCandidate, ProfilingRun.process_candidate_id == ProcessCandidate.id)
        .options(
            selectinload(ProfilingRun.process_candidate).selectinload(ProcessCandidate.candidate)
        )
        .order_by(ProfilingRun.created_at.desc())
    )

    if current_user.role == UserRole.RECRUITER.value:
        query = query.join(
            HiringProcess, ProcessCandidate.process_id == HiringProcess.id
        ).where(HiringProcess.recruiter_id == current_user.id)

    result = await db.execute(query)
    runs = list(result.scalars().all())

    return {
        "total": len(runs),
        "profiling_runs": [
            _serialize_run(run, _candidate_name(run))
            for run in runs
        ],
    }
