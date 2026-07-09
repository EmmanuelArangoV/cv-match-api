import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import RequireRecruiter, get_current_user
from src.domain.shared.exceptions import BusinessRuleException, NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    CandidateStatus,
    HiringProcess,
    ProcessStatus,
    User,
)

router = APIRouter(prefix="/processes", tags=["Match"])


@router.post("/{process_id}/match")
async def trigger_match(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from src.infrastructure.workers.tasks.run_match import run_match

    result = await db.execute(
        select(HiringProcess)
        .where(HiringProcess.id == process_id)
        .options(
            selectinload(HiringProcess.job_descriptions),
            selectinload(HiringProcess.process_candidates),
        )
    )
    process: HiringProcess | None = result.scalar_one_or_none()

    if not process:
        raise NotFoundException("Proceso no encontrado")

    # RB-009
    if process.status in (ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value):
        raise BusinessRuleException(
            "RB-009: No se pueden ejecutar acciones en un proceso cerrado o archivado"
        )

    # RB-001
    if not process.job_descriptions:
        raise BusinessRuleException("RB-001: El proceso no tiene una Job Description activa")

    eligible = [
        pc for pc in process.process_candidates if pc.status == CandidateStatus.MATCH_PENDING.value
    ]

    if not eligible:
        return {
            "process_id": str(process_id),
            "queued": 0,
            "message": "No hay candidatos con estado MATCH_PENDING para procesar",
        }

    process.status = ProcessStatus.MATCH_PROCESSING.value
    await db.commit()

    task_ids = []
    for pc in eligible:
        task = run_match.delay(
            process_candidate_id=str(pc.id),
            process_id=str(process_id),
        )
        task_ids.append(
            {
                "process_candidate_id": str(pc.id),
                "task_id": task.id,
            }
        )

    return {
        "process_id": str(process_id),
        "queued": len(task_ids),
        "tasks": task_ids,
    }


@router.get("/{process_id}/match/status")
async def match_status(
    process_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from src.infrastructure.db.models import ProcessCandidate

    result = await db.execute(select(HiringProcess).where(HiringProcess.id == process_id))
    process: HiringProcess | None = result.scalar_one_or_none()

    if not process:
        raise NotFoundException("Proceso no encontrado")

    pcs_result = await db.execute(
        select(ProcessCandidate).where(ProcessCandidate.process_id == process_id)
    )
    pcs = list(pcs_result.scalars().all())

    counts: dict[str, int] = {}
    for pc in pcs:
        counts[pc.status] = counts.get(pc.status, 0) + 1

    matched = counts.get(CandidateStatus.MATCHED.value, 0)
    pending = counts.get(CandidateStatus.MATCH_PENDING.value, 0)
    processing = counts.get(CandidateStatus.CV_PROCESSING.value, 0)
    error = counts.get(CandidateStatus.CV_ERROR.value, 0)
    total = len(pcs)

    progress_pct = round((matched / total * 100), 1) if total > 0 else 0

    return {
        "process_id": str(process_id),
        "process_status": process.status,
        "total_candidates": total,
        "matched": matched,
        "match_pending": pending,
        "cv_processing": processing,
        "errors": error,
        "progress_pct": progress_pct,
        "is_complete": process.status == ProcessStatus.MATCH_DONE.value,
    }
