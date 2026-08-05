from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    Candidate,
    HiringProcess,
    ProcessCandidate,
    QuestionSet,
    User,
    UserRole,
)

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("")
async def global_search(
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Busca procesos, candidatos y sets visibles para el usuario actual."""
    term = f"%{q.strip()}%"
    process_filter = (
        [HiringProcess.recruiter_id == current_user.id]
        if current_user.role == UserRole.RECRUITER.value
        else []
    )

    process_rows = await db.execute(
        select(HiringProcess)
        .where(
            *process_filter,
            or_(
                HiringProcess.name.ilike(term),
                HiringProcess.job_title.ilike(term),
                HiringProcess.area.ilike(term),
            ),
        )
        .order_by(HiringProcess.created_at.desc())
    )

    candidate_rows = await db.execute(
        select(ProcessCandidate, Candidate, HiringProcess)
        .join(Candidate, ProcessCandidate.candidate_id == Candidate.id)
        .join(HiringProcess, ProcessCandidate.process_id == HiringProcess.id)
        .where(
            *process_filter,
            or_(
                Candidate.name.ilike(term),
                Candidate.last_name.ilike(term),
                Candidate.email.ilike(term),
            ),
        )
        .order_by(ProcessCandidate.updated_at.desc())
    )

    set_rows = await db.execute(
        select(QuestionSet)
        .where(or_(QuestionSet.name.ilike(term), QuestionSet.description.ilike(term)))
        .order_by(QuestionSet.updated_at.desc())
    )

    all_results = (
        [("process", process) for process in process_rows.scalars().all()]
        + [("candidate", row) for row in candidate_rows.all()]
        + [("question_set", question_set) for question_set in set_rows.scalars().all()]
    )
    page_results = all_results[offset : offset + limit]

    return {
        "total": len(all_results),
        "limit": limit,
        "offset": offset,
        "processes": [
            {
                "id": str(process.id),
                "name": process.name,
                "job_title": process.job_title,
                "area": process.area,
            }
            for result_type, process in page_results
            if result_type == "process"
        ],
        "candidates": [
            {
                "process_id": str(process.id),
                "process_candidate_id": str(process_candidate.id),
                "name": f"{candidate.name} {candidate.last_name}".strip(),
                "email": candidate.email,
                "process_name": process.name,
            }
            for result_type, row in page_results
            if result_type == "candidate"
            for process_candidate, candidate, process in [row]
        ],
        "question_sets": [
            {
                "id": question_set.id.__str__(),
                "name": question_set.name,
                "description": question_set.description,
            }
            for result_type, question_set in page_results
            if result_type == "question_set"
        ],
    }
