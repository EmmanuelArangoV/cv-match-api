import logging
import uuid
from typing import Literal
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import NotificationModel, HiringProcess, CostLog

logger = logging.getLogger(__name__)

NotificationCategory = Literal[
    "BUDGET_50",
    "BUDGET_80",
    "BUDGET_EXCEEDED",
    "MATCH_COMPLETED",
    "PROFILING_COMPLETED",
    "PROFILING_FAILED",
    "CVS_PROCESSED",
    "PROCESS_CREATED",
    "SYSTEM_INFO",
]

NotificationType = Literal["INFO", "SUCCESS", "WARNING", "ALERT"]


def create_notification_sync(
    db: Session,
    title: str,
    description: str,
    category: NotificationCategory = "SYSTEM_INFO",
    type: NotificationType = "INFO",
    user_id: str | uuid.UUID | None = None,
    process_id: str | uuid.UUID | None = None,
    link: str | None = None,
) -> NotificationModel:
    """Crea una notificacion en la base de datos (sesion sincrona / Celery)."""
    user_uuid = uuid.UUID(str(user_id)) if user_id else None
    process_uuid = uuid.UUID(str(process_id)) if process_id else None

    notif = NotificationModel(
        user_id=user_uuid,
        process_id=process_uuid,
        category=category,
        type=type,
        title=title,
        description=description,
        link=link,
        is_read=False,
    )
    db.add(notif)
    db.flush()
    logger.info(f"[notification] creada notificacion [{category}] '{title}' para proceso {process_id}")
    return notif


async def create_notification_async(
    db: AsyncSession,
    title: str,
    description: str,
    category: NotificationCategory = "SYSTEM_INFO",
    type: NotificationType = "INFO",
    user_id: str | uuid.UUID | None = None,
    process_id: str | uuid.UUID | None = None,
    link: str | None = None,
) -> NotificationModel:
    """Crea una notificacion en la base de datos (sesion asincrona / FastAPI)."""
    user_uuid = uuid.UUID(str(user_id)) if user_id else None
    process_uuid = uuid.UUID(str(process_id)) if process_id else None

    notif = NotificationModel(
        user_id=user_uuid,
        process_id=process_uuid,
        category=category,
        type=type,
        title=title,
        description=description,
        link=link,
        is_read=False,
    )
    db.add(notif)
    await db.flush()
    logger.info(f"[notification] creada notificacion async [{category}] '{title}' para proceso {process_id}")
    return notif


def check_and_notify_budget_sync(db: Session, process_id: str | uuid.UUID) -> None:
    """Verifica el costo acumulado contra el presupuesto maximo y genera notificaciones de presupuesto (50%, 80%, Excedido)."""
    p_uuid = uuid.UUID(str(process_id))
    process = db.get(HiringProcess, p_uuid)
    if not process or not process.budget_max_usd or process.budget_max_usd <= 0:
        return

    # Sumar costos acumulados
    total_cost_res = db.execute(
        select(func.coalesce(func.sum(CostLog.estimated_cost), 0.0)).where(
            CostLog.process_id == p_uuid
        )
    ).scalar_one()

    total_cost = float(total_cost_res)
    budget = float(process.budget_max_usd)
    pct = (total_cost / budget) * 100.0

    # Obtener categorias de notificaciones ya creadas para este proceso
    existing_categories = set(
        db.execute(
            select(NotificationModel.category).where(
                NotificationModel.process_id == p_uuid,
                NotificationModel.category.in_(["BUDGET_50", "BUDGET_80", "BUDGET_EXCEEDED"]),
            )
        ).scalars().all()
    )

    link = f"/app/procesos/{p_uuid}"

    if pct >= 100.0 and "BUDGET_EXCEEDED" not in existing_categories:
        create_notification_sync(
            db,
            title="Presupuesto excedido",
            description=f"El proceso '{process.name}' superó el presupuesto configurado (${total_cost:.2f} / ${budget:.2f} USD).",
            category="BUDGET_EXCEEDED",
            type="ALERT",
            process_id=p_uuid,
            link=link,
        )
    elif pct >= 80.0 and "BUDGET_80" not in existing_categories:
        create_notification_sync(
            db,
            title="Presupuesto al 80%",
            description=f"El proceso '{process.name}' alcanzó el 80% de su presupuesto (${total_cost:.2f} / ${budget:.2f} USD).",
            category="BUDGET_80",
            type="WARNING",
            process_id=p_uuid,
            link=link,
        )
    elif pct >= 50.0 and "BUDGET_50" not in existing_categories:
        create_notification_sync(
            db,
            title="Presupuesto al 50%",
            description=f"El proceso '{process.name}' alcanzó el 50% de su presupuesto (${total_cost:.2f} / ${budget:.2f} USD).",
            category="BUDGET_50",
            type="WARNING",
            process_id=p_uuid,
            link=link,
        )
