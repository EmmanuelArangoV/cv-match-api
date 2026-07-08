import asyncio
import sys
import uuid
import os

# Fix for windows console unicode output
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Asegurar que la ruta base esté en el PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.infrastructure.db.database import AsyncSessionFactory, Base, engine
engine.echo = False
from src.infrastructure.db.models import (
    Candidate,
    HiringProcess,
    ProcessCandidate,
    WhatsAppConsentStatus,
    User,
    UserRole
)
from src.application.candidate.whatsapp_message_usecase import ProcessWhatsAppMessageUseCase
from src.infrastructure.messaging.whatsapp_client import whatsapp_client

# Monkey-patch para que Celery no intente conectarse a Redis si no está corriendo localmente
from src.infrastructure.workers.tasks.profiling import start_profiling_call
class MockCeleryResult:
    pass
def mock_apply_async(*args, **kwargs):
    print(f"\n⚙️ [Sistema]: (Simulado) Tarea 'start_profiling_call' enviada a Celery exitosamente (con delay de {kwargs.get('countdown', 0)}s).\n")
    return MockCeleryResult()

start_profiling_call.apply_async = mock_apply_async

# Monkey-patch para que el cliente de WhatsApp imprima en consola en lugar de intentar hacer HTTP real
async def mock_send_text_message(to_phone: str, message: str) -> dict:
    print(f"\n🤖 [Bot WhatsApp]: {message}\n")
    return {"status": "ok"}

whatsapp_client.send_text_message = mock_send_text_message

from src.infrastructure.workers.celery_app import celery_app

async def setup_dummy_data(db: AsyncSession) -> str:
    """Crea datos ficticios en la base de datos para simular la conversación."""
    # 1. Crear usuario (Recruiter)
    recruiter = User(
        name="Test",
        last_name="Recruiter",
        email=f"test_{uuid.uuid4()}@riwi.io",
        password_hash="mock",
        role=UserRole.RECRUITER.value
    )
    db.add(recruiter)
    await db.flush()

    # 2. Crear proceso de contratación
    process = HiringProcess(
        name="Proceso Backend Python",
        job_title="Senior Python Backend Engineer",
        area="Ingeniería",
        seniority="Senior",
        recruiter_id=recruiter.id
    )
    db.add(process)
    await db.flush()

    # 3. Crear candidato
    test_phone = "+573000000000"
    candidate = Candidate(
        name="Candidato",
        last_name="Prueba",
        email=f"candidato_{uuid.uuid4()}@example.com",
        phone=test_phone,
        cv_file_url="mock_url"
    )
    db.add(candidate)
    await db.flush()

    # 4. Crear ProcessCandidate pendiente
    pc = ProcessCandidate(
        process_id=process.id,
        candidate_id=candidate.id,
        whatsapp_consent_status=WhatsAppConsentStatus.PENDING.value
    )
    db.add(pc)
    await db.commit()
    
    return test_phone

async def main():
    print("==========================================================")
    print("🎙️ INICIANDO SIMULADOR DE CHAT DE WHATSAPP (RIWI MATCH) 🎙️")
    print("==========================================================")
    print("Creando datos de prueba en la base de datos local...")
    
    async with AsyncSessionFactory() as db:
        test_phone = await setup_dummy_data(db)
        
        print(f"\n✅ Datos creados. Simulando candidato con teléfono: {test_phone}")
        print("El sistema está esperando que le respondas al mensaje de consentimiento.")
        print("(Escribe 'salir' para terminar el chat)\n")
        
        use_case = ProcessWhatsAppMessageUseCase(db)
        
        while True:
            try:
                user_input = input("👤 [Tú]: ")
                if user_input.strip().lower() == "salir":
                    break
                    
                if not user_input.strip():
                    continue
                    
                # Ejecutar el caso de uso tal como lo haría el webhook real
                await use_case.execute(test_phone, user_input)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                break

    print("\n👋 Chat finalizado.")

if __name__ == "__main__":
    asyncio.run(main())
