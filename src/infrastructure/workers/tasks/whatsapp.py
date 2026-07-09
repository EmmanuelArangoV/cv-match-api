from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import selectinload, sessionmaker

from src.config import settings
from src.infrastructure.messaging.whatsapp_client import whatsapp_client
from src.infrastructure.workers.celery_app import celery_app

_engine = create_engine(settings.database_url_sync)
_SyncSession = sessionmaker(bind=_engine)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="send_whatsapp_consent")
def send_whatsapp_consent(self, process_candidate_id: str) -> dict:
    from src.infrastructure.db.models import ProcessCandidate

    pc_uuid = uuid.UUID(process_candidate_id)

    with _SyncSession() as db:
        try:
            from sqlalchemy import select

            pc: ProcessCandidate = db.execute(
                select(ProcessCandidate)
                .where(ProcessCandidate.id == pc_uuid)
                .options(
                    selectinload(ProcessCandidate.candidate),
                    selectinload(ProcessCandidate.process),
                )
            ).scalar_one_or_none()

            if not pc:
                return {"error": "ProcessCandidate no encontrado"}

            candidate = pc.candidate
            process = pc.process

            if not candidate or not candidate.phone:
                return {"skipped": "Candidato sin teléfono extraído — se omite WhatsApp"}

            res = asyncio.run(
                whatsapp_client.send_consent_template(
                    to_phone=candidate.phone,
                    candidate_name=f"{candidate.name} {candidate.last_name}".strip(),
                    job_title=process.job_title,
                )
            )

            pc.whatsapp_sent_at = datetime.now(UTC)
            
            from src.infrastructure.db.models import CostLog
            cost_log = CostLog(
                process_id=process.id,
                process_candidate_id=pc.id,
                action="WHATSAPP_CONSENT",
                provider="META",
                estimated_cost=0.08, # aprox cost per template
            )
            db.add(cost_log)
            db.commit()

            return {
                "status": "sent",
                "phone": candidate.phone,
                "candidate": f"{candidate.name} {candidate.last_name}",
                "job_title": process.job_title,
                "meta_response": res,
            }

        except Exception as exc:
            db.rollback()
            raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="resolve_whatsapp_timeouts")
def resolve_whatsapp_timeouts(self) -> dict:
    from datetime import timedelta

    from sqlalchemy import select

    from src.infrastructure.db.models import (
        ProcessCandidate,
        ProfilingRun,
        ProfilingRunStatus,
        WhatsAppConsentStatus,
    )
    from src.infrastructure.workers.tasks.profiling import start_profiling_call

    now = datetime.now(UTC)
    timeout_threshold = now - timedelta(hours=settings.whatsapp_consent_timeout_hours)

    with _SyncSession() as db:
        try:
            candidates = (
                db.execute(
                    select(ProcessCandidate)
                    .where(
                        ProcessCandidate.whatsapp_consent_status
                        == WhatsAppConsentStatus.PENDING.value
                    )
                    .where(ProcessCandidate.whatsapp_sent_at <= timeout_threshold)
                )
                .scalars()
                .all()
            )

            processed = []
            for pc in candidates:
                pc.whatsapp_consent_status = WhatsAppConsentStatus.TIMEOUT.value

                # Check if there is a queued profiling run waiting for consent
                run = db.execute(
                    select(ProfilingRun)
                    .where(ProfilingRun.process_candidate_id == pc.id)
                    .where(ProfilingRun.status == ProfilingRunStatus.QUEUED.value)
                ).scalar_one_or_none()

                if run:
                    # Inicia la llamada porque el timeout permite llamada en frío (RB-004 / WhatsApp logic)
                    start_profiling_call.delay(str(pc.id))
                    processed.append(str(pc.id))

            db.commit()
            return {"processed_count": len(processed), "processed_ids": processed}
        except Exception as exc:
            db.rollback()
            raise self.retry(exc=exc)
