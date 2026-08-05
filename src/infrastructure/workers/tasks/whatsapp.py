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
def send_whatsapp_consent(self, profiling_run_id: str) -> dict:
    from src.infrastructure.db.models import (
        ProcessCandidate,
        ProfilingRun,
        ProfilingRunStatus,
    )

    run_uuid = uuid.UUID(profiling_run_id)

    with _SyncSession() as db:
        try:
            from sqlalchemy import select

            run: ProfilingRun = db.execute(
                select(ProfilingRun)
                .where(ProfilingRun.id == run_uuid)
                .options(
                    selectinload(ProfilingRun.process_candidate).selectinload(
                        ProcessCandidate.candidate
                    ),
                    selectinload(ProfilingRun.process_candidate).selectinload(
                        ProcessCandidate.process
                    ),
                )
            ).scalar_one_or_none()

            if not run:
                return {"error": "ProfilingRun no encontrado"}
            if run.status != ProfilingRunStatus.PENDING.value:
                return {"status": run.status, "idempotent": True}

            pc = run.process_candidate
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

            from src.infrastructure.db.models import CostLog, OperationType

            cost_log = CostLog(
                process_id=process.id,
                candidate_id=candidate.id,
                operation_type=OperationType.WHATSAPP_MESSAGE.value,
                model_used="meta-whatsapp-template",
                estimated_cost=0.08,  # aprox cost per template
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

    from src.application.profiling.lifecycle import transition_profiling_sync
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
            runs = (
                db.execute(
                    select(ProfilingRun)
                    .join(
                        ProcessCandidate,
                        ProfilingRun.process_candidate_id == ProcessCandidate.id,
                    )
                    .where(
                        ProcessCandidate.whatsapp_consent_status
                        == WhatsAppConsentStatus.PENDING.value
                    )
                    .where(ProcessCandidate.whatsapp_sent_at <= timeout_threshold)
                    .where(ProfilingRun.status == ProfilingRunStatus.PENDING.value)
                    .options(selectinload(ProfilingRun.process_candidate))
                )
                .scalars()
                .all()
            )

            processed = []
            for run in runs:
                pc = run.process_candidate
                pc.whatsapp_consent_status = WhatsAppConsentStatus.TIMEOUT
                transition_profiling_sync(db, run, pc, ProfilingRunStatus.QUEUED)
                processed.append(str(run.id))

            db.commit()
            for run_id in processed:
                start_profiling_call.delay(run_id)
            return {"processed_count": len(processed), "processed_ids": processed}
        except Exception as exc:
            db.rollback()
            raise self.retry(exc=exc)
