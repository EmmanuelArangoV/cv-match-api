import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, func, update, delete, true
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import NotificationModel, User, HiringProcess, UserRole
from src.api.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["Notifications"])

BUDGET_CATEGORIES = ["BUDGET_50", "BUDGET_80", "BUDGET_EXCEEDED"]


def _build_user_notif_condition(current_user: User):
    if current_user.role == UserRole.RECRUITER.value:
        # Reclutadores:
        # 1. No ven notificaciones de presupuesto (solo Admin y Lider TA)
        # 2. Solo ven notificaciones de procesos creados por ellos mismos o dirigidas a su usuario
        return NotificationModel.category.not_in(BUDGET_CATEGORIES) & (
            (NotificationModel.user_id == current_user.id)
            | (NotificationModel.process.has(HiringProcess.recruiter_id == current_user.id))
        )

    # ADMIN y TA_LEADER:
    # Ven TODAS las notificaciones de TODOS los procesos y alertas del sistema
    return true()


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    process_id: uuid.UUID | None
    category: str
    type: str
    title: str
    description: str
    link: str | None
    is_read: bool
    created_at: str


class NotificationsListResponse(BaseModel):
    total: int
    unread_count: int
    notifications: list[NotificationOut]


@router.get("", response_model=NotificationsListResponse)
async def list_notifications(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
):
    """Retorna las notificaciones con scoping segun rol: Reclutador (solo sus procesos) vs Admin/Lider (presupuesto y globales)."""
    base_cond = _build_user_notif_condition(current_user)

    if unread_only:
        base_cond = base_cond & (NotificationModel.is_read.is_(False))

    # Total de notificaciones
    total_q = select(func.count(NotificationModel.id)).where(base_cond)
    total_res = await db.execute(total_q)
    total = total_res.scalar_one()

    # Total no leidas
    unread_q = select(func.count(NotificationModel.id)).where(
        base_cond & (NotificationModel.is_read.is_(False))
    )
    unread_res = await db.execute(unread_q)
    unread_count = unread_res.scalar_one()

    # Lista ordenada por fecha descendente
    query = (
        select(NotificationModel)
        .where(base_cond)
        .order_by(NotificationModel.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    res = await db.execute(query)
    items = res.scalars().all()

    serialized = [
        NotificationOut(
            id=item.id,
            user_id=item.user_id,
            process_id=item.process_id,
            category=item.category,
            type=item.type,
            title=item.title,
            description=item.description,
            link=item.link,
            is_read=item.is_read,
            created_at=item.created_at.isoformat(),
        )
        for item in items
    ]

    return NotificationsListResponse(
        total=total, unread_count=unread_count, notifications=serialized
    )


@router.patch("/{notification_id}/read", response_model=dict)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Marca una notificacion como leida."""
    stmt = (
        update(NotificationModel)
        .where(
            NotificationModel.id == notification_id,
            _build_user_notif_condition(current_user),
        )
        .values(is_read=True)
    )
    res = await db.execute(stmt)
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificación no encontrada o no pertenece al usuario",
        )
    return {"status": "success", "id": str(notification_id)}


@router.post("/read-all", response_model=dict)
async def mark_all_notifications_read(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Marca todas las notificaciones pendientes del usuario como leidas."""
    stmt = (
        update(NotificationModel)
        .where(
            _build_user_notif_condition(current_user)
            & (NotificationModel.is_read.is_(False))
        )
        .values(is_read=True)
    )
    res = await db.execute(stmt)
    await db.commit()
    return {"status": "success", "updated_count": res.rowcount}


@router.delete("/{notification_id}", response_model=dict)
async def delete_notification(
    notification_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Elimina una notificacion."""
    stmt = delete(NotificationModel).where(
        NotificationModel.id == notification_id,
        _build_user_notif_condition(current_user),
    )
    res = await db.execute(stmt)
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificación no encontrada",
        )
    return {"status": "deleted", "id": str(notification_id)}
