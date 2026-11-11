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
    ProcessAIPrompt,
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
Eres Valentina, entrevistadora de Riwi. Realizas una conversación breve de profiling para el
cargo de Líder Técnico de IA. Tu objetivo es entender experiencia real en liderazgo técnico,
arquitectura de productos de IA y operación responsable de modelos; no es un examen ni una venta.

Estilo de conversación:
- Saluda, confirma que hablas con la persona correcta y pide permiso explícito para continuar.
- Haz una pregunta a la vez. Espera la respuesta completa antes de continuar.
- Demuestra escucha con una frase corta y concreta que retome algo que la persona dijo; por
  ejemplo: "Entiendo, priorizaste trazabilidad porque el equipo debía auditar las respuestas.".
- Si una respuesta es ambigua, pide una precisión útil y breve: contexto, decisión, métrica o
  resultado. No repitas la respuesta, no inventes detalles y no uses elogios vacíos.
- Mantén un tono cercano, profesional y curioso. Evita jerga innecesaria y juicios sobre la
  persona. La llamada debe durar como máximo cinco minutos.

Al cerrar, agradece el tiempo, resume en una sola frase los dos o tres temas que entendiste y
explica que el equipo revisará el proceso. No prometas resultados ni fechas."""

FIRST_MESSAGE = (
    "Hola, ¿hablo con Angelo? Soy Valentina, de Riwi. Estamos conociendo perfiles para el cargo "
    "de Líder Técnico de IA. ¿Tienes unos cinco minutos para una conversación breve?"
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

        # Question set con la configuración técnica de voz reutilizable.
        question_set = QuestionSet(
            name="Profiling E2E - Líder Técnico de IA",
            description="Entrevista breve para validar liderazgo técnico y delivery de productos de IA.",
            status=QuestionSetStatus.ACTIVE.value,
            created_by=recruiter.id,
            default_language="es",
        )
        db.add(question_set)
        await db.flush()

        db.add_all(
            [
                ProfilingQuestion(
                    question_set_id=question_set.id,
                    order_index=0,
                    text=(
                        "Cuéntame de un producto de IA que hayas llevado a producción: "
                        "¿qué problema resolvía, qué decisión técnica lideraste y cómo mediste "
                        "que estaba aportando valor?"
                    ),
                    type=QuestionType.OPEN.value,
                    weight=10,
                    is_critical=False,
                ),
                ProfilingQuestion(
                    question_set_id=question_set.id,
                    order_index=1,
                    text=(
                        "Si un asistente con RAG empieza a dar respuestas plausibles pero "
                        "difíciles de verificar, ¿qué señales revisarías primero y qué cambio "
                        "priorizarías antes de escalarlo?"
                    ),
                    type=QuestionType.OPEN.value,
                    weight=20,
                    is_critical=True,
                ),
                ProfilingQuestion(
                    question_set_id=question_set.id,
                    order_index=2,
                    text=(
                        "Háblame de una decisión donde equilibraste calidad del modelo, latencia, "
                        "costo y privacidad. ¿Qué alternativa descartaste y por qué?"
                    ),
                    type=QuestionType.OPEN.value,
                    weight=20,
                    is_critical=True,
                ),
                ProfilingQuestion(
                    question_set_id=question_set.id,
                    order_index=3,
                    text=(
                        "Para un equipo con datos, backend y producto, ¿cómo organizarías las "
                        "primeras semanas para entregar una mejora de IA sin perder trazabilidad "
                        "ni calidad?"
                    ),
                    type=QuestionType.OPEN.value,
                    weight=15,
                    is_critical=False,
                ),
            ]
        )
        print(f"QuestionSet: {question_set.name} ({question_set.id})")

        # Hiring process con el question set asociado
        process = HiringProcess(
            name="Prueba E2E - Liderazgo Técnico IA",
            job_title="Líder Técnico de IA",
            area="Inteligencia Artificial",
            seniority="Lead",
            status=ProcessStatus.PROFILING_CONFIGURED.value,
            recruiter_id=recruiter.id,
            question_set_id=question_set.id,
        )
        db.add(process)
        await db.flush()
        # El prompt pertenece al proceso: este seed no depende de un default heredado
        # del question set ni de una plantilla global mutable.
        db.add(
            ProcessAIPrompt(
                process_id=process.id,
                task_type="VOICE_CALL_AGENT",
                version_name="qa-e2e",
                system_prompt_text=SYSTEM_PROMPT,
                first_message_text=FIRST_MESSAGE,
                is_active=True,
                created_by=recruiter.id,
            )
        )
        print(f"HiringProcess: {process.name} ({process.id})")

        # Candidato E2E reutilizable para que el seed sea idempotente.
        candidate = await db.scalar(select(Candidate).where(Candidate.email == CANDIDATE_EMAIL))
        if not candidate:
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
