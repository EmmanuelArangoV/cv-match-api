import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireRecruiter
from src.domain.shared.exceptions import NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import AIFeedback, ProcessCandidate, User

router = APIRouter(prefix="/feedback", tags=["AI Feedback"])

class CreateFeedbackRequest(BaseModel):
    process_candidate_id: uuid.UUID
    context: str = Field(..., description="MATCH o PROFILING")
    evaluation: str = Field(..., description="CORRECT, PARTIAL, INCORRECT")
    notes: str | None = None

@router.post("")
async def create_feedback(
    body: CreateFeedbackRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    pc = await db.get(ProcessCandidate, body.process_candidate_id)
    if not pc:
        raise NotFoundException("ProcessCandidate no encontrado")

    feedback = AIFeedback(
        process_candidate_id=body.process_candidate_id,
        context=body.context,
        evaluation=body.evaluation,
        notes=body.notes,
        created_by=current_user.id
    )
    db.add(feedback)
    await db.commit()

    return {"message": "Feedback registrado exitosamente"}
