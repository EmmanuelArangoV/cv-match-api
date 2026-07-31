from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireTALeader
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import CostLog, HiringProcess, ProcessCandidate, User, UserRole, UserStatus

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
    team_members_result = await db.execute(
        select(User)
        .where(
            User.role.in_([UserRole.RECRUITER, UserRole.TA_LEADER]),
            User.status == UserStatus.ACTIVE,
        )
        .order_by(User.name, User.last_name)
    )
    team_members = team_members_result.scalars().all()

    return {
        "total_processes": total_processes,
        "active_processes": active_processes,
        "total_candidates": total_candidates,
        "total_cost_usd": float(total_cost),
        "team_members": [
            {
                "id": str(member.id),
                "name": f"{member.name} {member.last_name}",
                "role": member.role.value
                if isinstance(member.role, UserRole)
                else member.role,
            }
            for member in team_members
        ],
    }
