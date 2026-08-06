import sys
import asyncio
import uuid
from pathlib import Path
from datetime import datetime, UTC

# Add Backend root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from src.infrastructure.db.database import AsyncSessionFactory
from src.infrastructure.db.models import (
    Candidate,
    ProcessCandidate,
    ProfilingRun,
    ProfilingAnswer,
    CandidateStatus,
    WhatsAppConsentStatus,
    ProfilingRunStatus,
)
from src.infrastructure.workers.tasks.whatsapp import send_whatsapp_consent


async def reset_and_trigger():
    phone_query = "%3185926525%"
    print(f"=== 1. Buscando candidato con teléfono {phone_query} ===")

    async with AsyncSessionFactory() as db:
        res = await db.execute(
            select(ProcessCandidate)
            .join(Candidate, ProcessCandidate.candidate_id == Candidate.id)
            .where(Candidate.phone.like(phone_query))
            .options(
                selectinload(ProcessCandidate.candidate),
                selectinload(ProcessCandidate.process),
                selectinload(ProcessCandidate.profiling_runs),
            )
            .order_by(ProcessCandidate.updated_at.desc())
        )
        pc = res.scalars().first()

        if not pc:
            print("ERROR: No se encontró ningún ProcessCandidate para ese número.")
            return

        candidate = pc.candidate
        process = pc.process
        print(f"✓ Encontrado Candidate ID: {candidate.id}")
        print(f"  Nombre: {candidate.name} {candidate.last_name}")
        print(f"  Teléfono: {candidate.phone}")
        print(f"  ProcessCandidate ID: {pc.id}")
        print(f"  Proceso: {process.job_title} (ID: {process.id})")
        print(f"  Estado actual PC: {pc.status}")
        print(f"  Consentimiento previo: {pc.whatsapp_consent_status}")
        print(f"  Corridas previas: {len(pc.profiling_runs)}")

        pc_id = pc.id
        question_set_id = process.question_set_id

        # 2. Eliminar ProfilingAnswers y ProfilingRuns
        print("\n=== 2. Eliminando ProfilingAnswer y ProfilingRun ===")
        # Obtener IDs de las corridas a eliminar
        run_ids = [run.id for run in pc.profiling_runs]
        if run_ids:
            ans_del = await db.execute(
                delete(ProfilingAnswer).where(ProfilingAnswer.profiling_run_id.in_(run_ids))
            )
            print(f"✓ ProfilingAnswer eliminadas: {ans_del.rowcount}")

        runs_del = await db.execute(
            delete(ProfilingRun).where(ProfilingRun.process_candidate_id == pc_id)
        )
        print(f"✓ ProfilingRun eliminadas: {runs_del.rowcount}")

        # 3. Resetear la fila de ProcessCandidate
        print("\n=== 3. Reseteando ProcessCandidate ===")
        pc.status = CandidateStatus.MATCHED.value
        pc.whatsapp_consent_status = WhatsAppConsentStatus.PENDING.value
        pc.whatsapp_sent_at = None
        pc.whatsapp_responded_at = None
        pc.availability_preference = None
        pc.whatsapp_conversation = None

        print("✓ Campos reseteados:")
        print(f"  - status: {pc.status}")
        print(f"  - whatsapp_consent_status: {pc.whatsapp_consent_status}")
        print("  - whatsapp_sent_at: None")
        print("  - whatsapp_responded_at: None")
        print("  - availability_preference: None")
        print("  - whatsapp_conversation: None")

        # 4. Crear nueva corrida ProfilingRun en PENDING y guardar
        print("\n=== 4. Creando nueva ProfilingRun ===")
        new_run = ProfilingRun(
            process_candidate_id=pc_id,
            question_set_id=question_set_id,
            status=ProfilingRunStatus.PENDING.value,
        )
        db.add(new_run)
        await db.commit()
        await db.refresh(new_run)
        new_run_id = str(new_run.id)
        print(f"✓ Nueva ProfilingRun creada con ID: {new_run_id}")

    # 5. Ejecutar envío de mensaje de consentimiento WhatsApp
    print("\n=== 5. Disparando tarea send_whatsapp_consent ===")
    try:
        # Enviar vía Celery task (.delay)
        celery_task = send_whatsapp_consent.delay(new_run_id)
        print(f"✓ Tarea Celery enviada a cola. Task ID: {celery_task.id}")
    except Exception as e:
        print(f"⚠️ Advertencia al enviar via Celery .delay(): {e}")

    # También ejecutar sincrónicamente via .apply(...) para capturar el resultado directo de Meta API
    try:
        print("Ejecutando task.apply() para confirmación inmediata de WhatsApp API...")
        res = send_whatsapp_consent.apply(args=[new_run_id])
        result = res.result
        print(f"✓ Resultado del envío por WhatsApp: {result}")
    except Exception as e:
        print(f"❌ Error durante la ejecución directa de la tarea WhatsApp: {e}")

    print("\n=== PROCESO DE RESET Y DISPARO COMPLETADO CON ÉXITO ===")


if __name__ == "__main__":
    asyncio.run(reset_and_trigger())
