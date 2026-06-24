from __future__ import annotations
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.infrastructure.workers.celery_app import celery_app
from src.infrastructure.messaging.whatsapp_client import whatsapp_client

_engine = create_engine(settings.database_url_sync)
_SyncSession = sessionmaker(bind=_engine)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="send_whatsapp_consent")
def send_whatsapp_consent(self, process_candidate_id: str) -> dict:
    from src.infrastructure.db.models import ProcessCandidate
    
    pc_uuid = uuid.UUID(process_candidate_id)
    
    with _SyncSession() as db:
        try:
            pc: ProcessCandidate = db.get(ProcessCandidate, pc_uuid)
            if not pc or not pc.candidate or not pc.candidate.phone:
                return {"error": "Candidato sin teléfono o no encontrado"}
            
            # Enviar plantilla
            # Asumimos que la plantilla se llama "consentimiento_entrevista" 
            import asyncio
            res = asyncio.run(
                whatsapp_client.send_template_message(
                    to_phone=pc.candidate.phone, 
                    template_name="consentimiento_entrevista"
                )
            )
            
            from datetime import datetime, timezone
            pc.whatsapp_sent_at = datetime.now(timezone.utc)
            db.commit()
            
            return {"status": "sent", "phone": pc.candidate.phone, "response": res}
        except Exception as exc:
            db.rollback()
            raise self.retry(exc=exc)
