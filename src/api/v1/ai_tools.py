from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireRecruiter
from src.application.ai.enhance_jd_usecase import EnhanceJDUseCase
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import User

router = APIRouter(prefix="/ai-tools", tags=["AI Tools"])

class EnhanceJDRequest(BaseModel):
    draft_text: str = Field(..., min_length=10, description="El borrador inicial del Job Description")

@router.post("/enhance-jd")
async def enhance_job_description(
    body: EnhanceJDRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db)
) -> dict:
    use_case = EnhanceJDUseCase(db)
    enhanced_text = await use_case.execute(body.draft_text, current_user.id)
    return {"enhanced_text": enhanced_text}
