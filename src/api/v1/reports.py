from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireTALeader
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import CostLog, HiringProcess, ProcessCandidate, User

router = APIRouter(prefix="/reports", tags=["Reports"])

@router.get("/ta-dashboard")
async def get_ta_dashboard(
    current_user: User = RequireTALeader,
    db: AsyncSession = Depends(get_db)
) -> dict:
    total_processes = await db.scalar(select(func.count(HiringProcess.id)))
    active_processes = await db.scalar(select(func.count(HiringProcess.id)).where(HiringProcess.status != 'CLOSED', HiringProcess.status != 'ARCHIVED'))
    total_candidates = await db.scalar(select(func.count(ProcessCandidate.id)))
    total_cost = await db.scalar(select(func.sum(CostLog.estimated_cost))) or 0.0

    return {
        "total_processes": total_processes,
        "active_processes": active_processes,
        "total_candidates": total_candidates,
        "total_cost_usd": float(total_cost)
    }
