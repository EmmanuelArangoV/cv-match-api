from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireRecruiter
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import CostLog, HiringProcess, User

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/dashboard")
async def get_metrics_dashboard(
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Agrega CostLog por proceso, usuario, tipo de operación y día."""
    total_result = await db.execute(select(func.coalesce(func.sum(CostLog.estimated_cost), 0)))
    total_cost_usd = float(total_result.scalar_one())

    by_process_result = await db.execute(
        select(
            CostLog.process_id,
            HiringProcess.name,
            func.sum(CostLog.estimated_cost),
            func.count(func.distinct(CostLog.candidate_id)),
        )
        .join(HiringProcess, CostLog.process_id == HiringProcess.id)
        .group_by(CostLog.process_id, HiringProcess.name)
        .order_by(func.sum(CostLog.estimated_cost).desc())
    )
    cost_by_process = [
        {
            "process_id": str(process_id),
            "process_name": name,
            "total_cost": float(total),
            "candidate_count": count,
        }
        for process_id, name, total, count in by_process_result.all()
    ]

    by_user_result = await db.execute(
        select(
            CostLog.user_id,
            User.name,
            User.last_name,
            func.sum(CostLog.estimated_cost),
        )
        .join(User, CostLog.user_id == User.id)
        .group_by(CostLog.user_id, User.name, User.last_name)
        .order_by(func.sum(CostLog.estimated_cost).desc())
    )
    cost_by_user = [
        {
            "user_id": str(user_id),
            "user_name": f"{name} {last_name}",
            "total_cost": float(total),
        }
        for user_id, name, last_name, total in by_user_result.all()
    ]

    by_operation_result = await db.execute(
        select(
            CostLog.operation_type,
            func.sum(CostLog.estimated_cost),
            func.count(CostLog.id),
        ).group_by(CostLog.operation_type)
    )
    cost_by_operation = [
        {
            "operation_type": operation_type,
            "total_cost": float(total),
            "count": count,
        }
        for operation_type, total, count in by_operation_result.all()
    ]

    daily_result = await db.execute(
        select(
            func.date_trunc("day", CostLog.created_at).label("day"),
            func.sum(CostLog.estimated_cost),
        )
        .group_by("day")
        .order_by("day")
    )
    daily_costs = [
        {"date": day.date().isoformat(), "cost": float(total)}
        for day, total in daily_result.all()
    ]

    return {
        "total_cost_usd": total_cost_usd,
        "cost_by_process": cost_by_process,
        "cost_by_user": cost_by_user,
        "cost_by_operation": cost_by_operation,
        "daily_costs": daily_costs,
    }
