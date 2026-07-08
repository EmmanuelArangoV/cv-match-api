"""
Seed script: crea todos los datos necesarios para una prueba real de extremo a extremo
de llamadas de voz (Twilio + ElevenLabs) — recruiter, question set con config de voz,
hiring process, candidato y process_candidate en PROFILING_QUEUED, listo para disparar
con POST /api/v1/debug/trigger-profiling-call/{process_candidate_id}.

Uso:
  source venv/bin/activate
  python scripts/seed_voice_e2e_test.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import bcrypt
from sqlalchemy import select

from src.infrastructure.db.database import AsyncSessionFactory
from src.infrastructure.db.models import (
    Candidate,
    CandidateStatus,
    HiringProcess,
    ProcessCandidate,
    ProcessStatus,
    ProfilingQuestion,
    QuestionSet,
    QuestionSetStatus,
    QuestionType,
    User,
    UserRole,
    UserStatus,
    WhatsAppConsentStatus,
)

CANDIDATE_NAME = "Angelo"
CANDIDATE_LAST_NAME = "Gaviria"
CANDIDATE_PHONE = "+573147573205"
CANDIDATE_EMAIL = "angelo.gaviria.e2e@riwi.io"

RECRUITER_EMAIL = "recruiter-test@riwi.io"

SYSTEM_PROMPT = """\
Eres un agente de voz de Riwi Corp llamando a un candidato para una entrevista breve de
profiling despues de un proceso de seleccion para un cargo de Desarrollador Backend.
Preséntate, pide consentimiento explícito para continuar la llamada, y si acepta, haz
las preguntas del cuestionario de forma natural y conversacional. Sé cálido, profesional
y breve — la llamada no debe durar más de 5 minutos."""

FIRST_MESSAGE = (
    "Hola, ¿hablo con Angelo? Te llamo de parte de Riwi Corp para una breve entrevista "
    "de seguimiento sobre tu proceso de selección. ¿Tienes un par de minutos?"
)


async def main() -> None:
    async with AsyncSessionFactory() as db:
        # Recruiter de prueba (reusable)
        result = await db.execute(select(User).where(User.email == RECRUITER_EMAIL))
        recruiter = result.scalar_one_or_none()
        if not recruiter:
            recruiter = User(
                name="Recruiter",
                last_name="Test",
                email=RECRUITER_EMAIL,
                password_hash=bcrypt.hashpw(b"test1234", bcrypt.gensalt()).decode(),
                role=UserRole.RECRUITER.value,
                status=UserStatus.ACTIVE.value,
            )
            db.add(recruiter)
            await db.flush()
        print(f"Recruiter: {recruiter.email} ({recruiter.id})")

        # Question set con config de voz (system prompt / first message dinamicos)
        question_set = QuestionSet(
            name="Profiling E2E Test - Voz",
            description="Set de prueba para validar la integracion real Twilio + ElevenLabs",
            status=QuestionSetStatus.ACTIVE.value,
            created_by=recruiter.id,
            default_system_prompt=SYSTEM_PROMPT,
            default_first_message=FIRST_MESSAGE,
            default_language="es",
        )
        db.add(question_set)
        await db.flush()

        db.add_all(
            [
                ProfilingQuestion(
                    question_set_id=question_set.id,
                    order_index=0,
                    text="¿Cuál dirías que es tu mayor fortaleza técnica como desarrollador backend?",
                    type=QuestionType.OPEN.value,
                    weight=10,
                    is_critical=False,
                ),
                ProfilingQuestion(
                    question_set_id=question_set.id,
                    order_index=1,
                    text="¿Tienes disponibilidad para trabajar tiempo completo de forma remota?",
                    type=QuestionType.YES_NO.value,
                    expected_answer="sí",
                    weight=15,
                    is_critical=True,
                ),
            ]
        )
        print(f"QuestionSet: {question_set.name} ({question_set.id})")

        # Hiring process con el question set asociado
        process = HiringProcess(
            name="Prueba E2E Llamadas de Voz",
            job_title="Desarrollador Backend",
            area="Tecnologia",
            seniority="Senior",
            status=ProcessStatus.PROFILING_CONFIGURED.value,
            recruiter_id=recruiter.id,
            question_set_id=question_set.id,
        )
        db.add(process)
        await db.flush()
        print(f"HiringProcess: {process.name} ({process.id})")

        # Candidato
        candidate = Candidate(
            name=CANDIDATE_NAME,
            last_name=CANDIDATE_LAST_NAME,
            email=CANDIDATE_EMAIL,
            phone=CANDIDATE_PHONE,
            cv_file_url="",
        )
        db.add(candidate)
        await db.flush()
        print(f"Candidate: {candidate.name} {candidate.last_name} ({candidate.phone})")

        # ProcessCandidate ya en PROFILING_QUEUED, listo para disparar la llamada
        pc = ProcessCandidate(
            process_id=process.id,
            candidate_id=candidate.id,
            status=CandidateStatus.PROFILING_QUEUED.value,
            match_percentage=90.0,
            whatsapp_consent_status=WhatsAppConsentStatus.ACCEPTED.value,
        )
        db.add(pc)
        await db.commit()

        print("\n--- Listo ---")
        print(f"process_candidate_id: {pc.id}")
        print(
            "\nDisparar con:\n"
            f"  curl -X POST http://localhost:8001/api/v1/debug/trigger-profiling-call/{pc.id}"
        )


if __name__ == "__main__":
    asyncio.run(main())
