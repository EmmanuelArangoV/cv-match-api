from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireAdmin
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import AuditLog, User

router = APIRouter(prefix="/audit-logs", tags=["Audit"])

@router.get("")
async def list_audit_logs(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    action: str | None = None,
    entity_type: str | None = None,
    current_user: User = RequireAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    query = (
        select(AuditLog, User.name.label("user_name"), User.last_name.label("user_last_name"))
        .outerjoin(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.created_at.desc())
    )

    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)

    result = await db.execute(query.offset(offset).limit(limit))
    rows = result.all()

    return {
        "limit": limit,
        "offset": offset,
        "logs": [
            {
                "id": str(log.id),
                "user_id": str(log.user_id) if log.user_id else None,
                "user_name": f"{user_name or ''} {user_last_name or ''}".strip() or None,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": str(log.entity_id) if log.entity_id else None,
                "old_value": log.old_value,
                "new_value": log.new_value,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat(),
            }
            for log, user_name, user_last_name in rows
        ]
    }
