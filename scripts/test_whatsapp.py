import asyncio
import uuid
from sqlalchemy import select
from src.infrastructure.db.database import AsyncSessionFactory
from src.infrastructure.db.models import Candidate, HiringProcess, ProcessCandidate, WhatsAppConsentStatus, ProcessStatus, CandidateStatus, User, UserRole
from src.infrastructure.messaging.whatsapp_client import whatsapp_client

async def test_whatsapp(phone_number: str):
    async with AsyncSessionFactory() as session:
        # Obtener o crear un reclutador
        user = (await session.execute(select(User))).scalars().first()
        if not user:
            user = User(
                id=uuid.uuid4(),
                name="Recruiter",
                last_name="Test",
                email="recruiter@test.com",
                password_hash="hash",
                role=UserRole.ADMIN
            )
            session.add(user)
            await session.flush()

        # 1. Crear proceso de prueba
        process_id = uuid.uuid4()
        process = HiringProcess(
            id=process_id,
            name="Proceso de Prueba",
            job_title="Desarrollador Backend (Test)",
            area="IT",
            seniority="Senior",
            recruiter_id=user.id,
            status=ProcessStatus.MATCH_PROCESSING
        )
        session.add(process)

        # 2. Crear candidato de prueba
        candidate_id = uuid.uuid4()
        candidate = Candidate(
            id=candidate_id,
            name="Usuario",
            last_name="De Prueba",
            email=f"prueba_{candidate_id.hex[:6]}@riwi.io",
            phone=phone_number,
            cv_file_url="test.pdf"
        )
        session.add(candidate)

        # 3. Vincularlos con estado PENDING para el webhook
        pc_id = uuid.uuid4()
        pc = ProcessCandidate(
            id=pc_id,
            candidate_id=candidate_id,
            process_id=process_id,
            status=CandidateStatus.MATCH_PENDING,
            whatsapp_consent_status=WhatsAppConsentStatus.PENDING
        )
        session.add(pc)

        await session.commit()
        print(f"Datos de prueba creados en BD. ProcessCandidate ID: {pc_id}")

        # 4. Enviar la plantilla real aprobada (autorizacion_llamada_ia_v2)
        # usando el cliente directamente, para no depender de Celery aquí.
        candidate_name = f"{candidate.name} {candidate.last_name}".strip()
        print(f"Enviando plantilla 'autorizacion_llamada_ia_v2' a {phone_number}...")
        res = await whatsapp_client.send_consent_template(
            to_phone=phone_number,
            candidate_name=candidate_name,
            job_title=process.job_title,
        )
        print(f"Mensaje enviado! Respuesta de Meta: {res}")
        print("\n¡Revisa tu celular! Cuando respondas el mensaje, el webhook de Ngrok lo recibirá y OpenAI te contestará.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python scripts/test_whatsapp.py <TU_NUMERO_CON_CODIGO_DE_PAIS>")
        print("Ejemplo: python scripts/test_whatsapp.py 573001234567")
        sys.exit(1)
        
    asyncio.run(test_whatsapp(sys.argv[1]))
