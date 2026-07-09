import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from src.infrastructure.db.models import AuditLog

def record_audit(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    ip_address: str | None = None,
) -> None:
    '''
    Registra una accion de auditoria en la tabla AuditLog.
    La insercion no hace commit automatico; depende del commit de la transaccion actual.
    '''
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
    )
    session.add(log)
