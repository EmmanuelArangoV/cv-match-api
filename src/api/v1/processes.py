import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import RequireRecruiter, RequireTALeader, get_current_user
from src.domain.shared.exceptions import BusinessRuleException, NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    HiringProcess,
    JobDescription,
    ProcessStatus,
    User,
)

router = APIRouter(prefix="/processes", tags=["Processes"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateProcessRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    job_title: str = Field(..., min_length=1, max_length=255)
    area: str = Field(..., min_length=1, max_length=100)
    seniority: str = Field(..., min_length=1, max_length=50)
    budget_max_usd: float = Field(default=0.0, ge=0)
    match_weights_override: dict | None = None


class CreateJobDescriptionRequest(BaseModel):
    jd_raw_text: str = Field(..., min_length=10)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_process(
    body: CreateProcessRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from src.domain.match.value_objects import MatchWeights

    # Validar pesos si se envían
    if body.match_weights_override:
        MatchWeights.from_dict(body.match_weights_override)

    process = HiringProcess(
        name=body.name,
        job_title=body.job_title,
        area=body.area,
        seniority=body.seniority,
        budget_max_usd=body.budget_max_usd,
        match_weights_override=body.match_weights_override,
        recruiter_id=current_user.id,
        status=ProcessStatus.DRAFT.value,
    )
    db.add(process)
    await db.commit()
    await db.refresh(process)

    return {
        "process_id": str(process.id),
        "name": process.name,
        "job_title": process.job_title,
        "area": process.area,
        "seniority": process.seniority,
        "status": process.status,
        "budget_max_usd": float(process.budget_max_usd),
    }


@router.get("")
async def list_processes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from src.infrastructure.db.models import UserRole

    query = select(HiringProcess).order_by(HiringProcess.created_at.desc())

    # RECRUITER solo ve los suyos
    if current_user.role == UserRole.RECRUITER.value:
        query = query.where(HiringProcess.recruiter_id == current_user.id)

    result = await db.execute(query)
    processes = list(result.scalars().all())

    return {
        "total": len(processes),
        "processes": [
            {
                "process_id": str(p.id),
                "name": p.name,
                "job_title": p.job_title,
                "area": p.area,
                "seniority": p.seniority,
                "status": p.status,
                "budget_max_usd": float(p.budget_max_usd),
                "created_at": p.created_at.isoformat(),
            }
            for p in processes
        ],
    }


@router.get("/{process_id}")
async def get_process(
    process_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(HiringProcess)
        .where(HiringProcess.id == process_id)
        .options(selectinload(HiringProcess.job_descriptions))
    )
    process: HiringProcess | None = result.scalar_one_or_none()

    if not process:
        raise NotFoundException("Proceso no encontrado")

    jds = sorted(process.job_descriptions, key=lambda j: j.version, reverse=True)
    active_jd = jds[0] if jds else None

    return {
        "process_id": str(process.id),
        "name": process.name,
        "job_title": process.job_title,
        "area": process.area,
        "seniority": process.seniority,
        "status": process.status,
        "budget_max_usd": float(process.budget_max_usd),
        "match_weights": process.match_weights_override,
        "job_description": {
            "jd_id": str(active_jd.id),
            "version": active_jd.version,
            "text_preview": active_jd.jd_raw_text[:300] + "..." if len(active_jd.jd_raw_text) > 300 else active_jd.jd_raw_text,
            "created_at": active_jd.created_at.isoformat(),
        } if active_jd else None,
        "created_at": process.created_at.isoformat(),
        "updated_at": process.updated_at.isoformat(),
    }


@router.post("/{process_id}/job-description", status_code=201)
async def create_job_description(
    process_id: uuid.UUID,
    body: CreateJobDescriptionRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(HiringProcess)
        .where(HiringProcess.id == process_id)
        .options(selectinload(HiringProcess.job_descriptions))
    )
    process: HiringProcess | None = result.scalar_one_or_none()

    if not process:
        raise NotFoundException("Proceso no encontrado")

    if process.status in (ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value):
        raise BusinessRuleException("RB-009: Proceso cerrado o archivado")

    # Versión incremental
    next_version = max((jd.version for jd in process.job_descriptions), default=0) + 1

    jd = JobDescription(
        process_id=process_id,
        version=next_version,
        jd_raw_text=body.jd_raw_text,
        structured_jd={"version": next_version, "raw": body.jd_raw_text},
    )
    db.add(jd)
    await db.commit()
    await db.refresh(jd)

    return {
        "jd_id": str(jd.id),
        "process_id": str(process_id),
        "version": jd.version,
        "created_at": jd.created_at.isoformat(),
    }
