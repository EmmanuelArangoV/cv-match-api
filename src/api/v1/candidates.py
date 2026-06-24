import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user
from src.application.cv.use_cases import UploadCVsUseCase
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import User

router = APIRouter(prefix="/processes", tags=["Candidates"])


@router.post("/{process_id}/candidates/upload")
async def upload_cvs(
    process_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
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
    from src.infrastructure.db.repositories.candidate_repository import CandidateRepository

    repo = CandidateRepository(db)
    pcs = await repo.find_process_candidates(process_id)

    return {
        "process_id": str(process_id),
        "total": len(pcs),
        "candidates": [
            {
                "process_candidate_id": str(pc.id),
                "candidate_id": str(pc.candidate_id),
                "name": f"{pc.candidate.name} {pc.candidate.last_name}",
                "email": pc.candidate.email,
                "phone": pc.candidate.phone,
                "status": pc.status,
                "match_percentage": float(pc.match_percentage),
                "match_category": pc.match_category,
                "whatsapp_consent": pc.whatsapp_consent_status,
            }
            for pc in pcs
        ],
    }
