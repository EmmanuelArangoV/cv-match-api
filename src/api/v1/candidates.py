import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireRecruiter, get_current_user
from src.application.cv.use_cases import UploadCVsUseCase
from src.domain.shared.exceptions import NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import User
from src.infrastructure.db.repositories.candidate_repository import CandidateRepository

router = APIRouter(prefix="/processes", tags=["Candidates"])


@router.post("/{process_id}/candidates/upload")
async def upload_cvs(
    process_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    use_case = UploadCVsUseCase(db)
    results = await use_case.execute(
        process_id=process_id,
        files=files,
        uploader_id=current_user.id,
    )
    await db.commit()

    return {
        "uploaded": len(results),
        "candidates": [
            {
                "candidate_id": str(r.candidate_id),
                "process_candidate_id": str(r.process_candidate_id),
                "filename": r.filename,
                "task_id": r.task_id,
                "status": "LOADED",
            }
            for r in results
        ],
    }


@router.get("/{process_id}/candidates")
async def list_candidates(
    process_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    repo = CandidateRepository(db)
    pcs = await repo.find_process_candidates(process_id)

    candidates = []
    for rank, pc in enumerate(pcs, start=1):
        explanation = pc.match_explanation or {}
        entry = {
            "rank": rank,
            "process_candidate_id": str(pc.id),
            "candidate_id": str(pc.candidate_id),
            "name": f"{pc.candidate.name} {pc.candidate.last_name}",
            "email": pc.candidate.email,
            "phone": pc.candidate.phone,
            "status": pc.status,
            "match_percentage": float(pc.match_percentage),
            "match_category": pc.match_category,
            "whatsapp_consent": pc.whatsapp_consent_status,
            "normalized_cv_url": pc.candidate.normalized_cv_url,
        }
        # Añadir resumen del match si ya fue procesado
        if explanation:
            entry["match_summary"] = explanation.get("summary")
            entry["strengths"] = explanation.get("strengths", [])
            entry["gaps"] = explanation.get("gaps", [])
        candidates.append(entry)

    return {
        "process_id": str(process_id),
        "total": len(candidates),
        "candidates": candidates,
    }


@router.get("/{process_id}/candidates/{process_candidate_id}")
async def get_candidate_detail(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    explanation = pc.match_explanation or {}
    candidate = pc.candidate

    return {
        "process_candidate_id": str(pc.id),
        "process_id": str(process_id),
        "candidate": {
            "candidate_id": str(candidate.id),
            "name": f"{candidate.name} {candidate.last_name}",
            "email": candidate.email,
            "phone": candidate.phone,
            "cv_url": candidate.cv_file_url,
            "normalized_cv_url": candidate.normalized_cv_url,
            "profile": candidate.normalized_cv,
        },
        "status": pc.status,
        "whatsapp_consent": pc.whatsapp_consent_status,
        "human_notes": pc.human_notes,
        "human_override_match": float(pc.human_override_match) if pc.human_override_match else None,
        "match": {
            "percentage": float(pc.match_percentage),
            "category": pc.match_category,
            "summary": explanation.get("summary"),
            "strengths": explanation.get("strengths", []),
            "gaps": explanation.get("gaps", []),
            "breakdown": explanation.get("breakdown", {}),
        } if pc.match_percentage else None,
    }
