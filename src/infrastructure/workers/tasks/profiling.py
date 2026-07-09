import json
import logging
import uuid
from datetime import UTC, datetime

from celery import shared_task
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.application.profiling.use_cases import (
    InitiateProfilingCallUseCase,
    RetryOrFailProfilingCallUseCase,
)
from src.config import settings
from src.domain.profiling.value_objects import AdvancementProbability as AdvancementProbabilityVO
from src.domain.profiling.watchdog import WATCHED_STATUSES, is_run_stale
from src.domain.shared.exceptions import BusinessRuleException, DomainException, NotFoundException
from src.infrastructure.db.models import (
    AdvancementProbability,
    ProfilingAnswer,
    ProfilingQuestion,
    ProfilingRun,
    QuestionSet,
)

_engine = create_engine(settings.database_url_sync)
_SyncSession = sessionmaker(bind=_engine)

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="start_profiling_call")
def start_profiling_call(self, process_candidate_id: str):
    """Inicia una llamada saliente de profiling hacia el candidato (Twilio + ElevenLabs)."""
    with _SyncSession() as db:
        try:
            profiling_run = InitiateProfilingCallUseCase(db).execute(process_candidate_id)
            db.commit()
            return {
                "status": "CALLING",
                "profiling_run_id": str(profiling_run.id),
                "twilio_call_sid": profiling_run.twilio_call_sid,
            }
        except (BusinessRuleException, NotFoundException, DomainException) as exc:
            # Errores de negocio: no son transitorios, no tiene sentido reintentar.
            db.rollback()
            logger.warning(f"[profiling] no se inicio llamada para {process_candidate_id}: {exc}")
            return {"error": str(exc)}
        except Exception as exc:
            db.rollback()
            logger.error(f"[profiling] error transitorio iniciando llamada: {exc}")
            raise self.retry(exc=exc, max_retries=settings.max_call_attempts)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="retry_or_fail_profiling_call")
def retry_or_fail_profiling_call(self, profiling_run_id: str, reason: str):
    """Reintenta una llamada sin conectar, o marca PROFILING_FAILED si se agotaron los intentos."""
    with _SyncSession() as db:
        try:
            run = RetryOrFailProfilingCallUseCase(db).execute(profiling_run_id, reason)
            db.commit()
            return {"status": run.status, "call_attempts": run.call_attempts}
        except (BusinessRuleException, NotFoundException, DomainException) as exc:
            db.rollback()
            logger.warning(f"[profiling] no se pudo reintentar {profiling_run_id}: {exc}")
            return {"error": str(exc)}
        except Exception as exc:
            db.rollback()
            logger.error(f"[profiling] error transitorio reintentando llamada: {exc}")
            raise self.retry(exc=exc, max_retries=settings.max_call_attempts)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="check_stale_profiling_calls")
def check_stale_profiling_calls(self):
    """
    Watchdog periodico (disparado por Celery Beat). Cubre el caso en que un
    ProfilingRun queda atascado en CALLING (nunca llego el status callback de
    Twilio) o en ANSWERED (un humano contesto pero el webhook nativo de
    post-call de ElevenLabs nunca llego — p.ej. el callee cuelga durante el
    aire muerto antes de que el agente conecte). Sin esto esos
    ProcessCandidate quedan varados para siempre en PROFILING_CALLING.

    Primero se hace una lectura barata (sin lock) para descartar la mayoria
    de los runs activos; solo los que ya parecen atascados se bloquean uno a
    uno con SELECT ... FOR UPDATE SKIP LOCKED y se re-evaluan bajo el lock
    (por si un webhook real los cerro justo entre la lectura y el lock, o ya
    los esta procesando otro worker).
    """
    now = datetime.now(UTC)
    calling_timeout = settings.stale_calling_timeout_seconds
    answered_timeout = settings.stale_answered_timeout_seconds

    with _SyncSession() as db:
        try:
            candidates = db.execute(
                select(ProfilingRun.id, ProfilingRun.status, ProfilingRun.started_at).where(
                    ProfilingRun.status.in_(WATCHED_STATUSES)
                )
            ).all()

            processed = []
            for run_id, status, started_at in candidates:
                if not is_run_stale(status, started_at, now, calling_timeout, answered_timeout):
                    continue

                locked = db.execute(
                    select(ProfilingRun)
                    .where(ProfilingRun.id == run_id)
                    .with_for_update(skip_locked=True)
                ).scalar_one_or_none()
                if not locked:
                    continue  # otro worker lo tiene bloqueado ahora mismo (p.ej. un webhook)
                if not is_run_stale(
                    locked.status, locked.started_at, now, calling_timeout, answered_timeout
                ):
                    continue  # se resolvio entre la lectura y el lock

                RetryOrFailProfilingCallUseCase(db).execute(str(locked.id), "watchdog_timeout")
                processed.append(str(locked.id))

            db.commit()
            if processed:
                logger.warning(f"[watchdog] runs atascados procesados: {processed}")
            return {"processed": processed}
        except Exception as exc:
            db.rollback()
            logger.error(f"[watchdog] error revisando llamadas atascadas: {exc}")
            raise self.retry(exc=exc, max_retries=settings.max_call_attempts)


@shared_task(
    bind=True, max_retries=3, default_retry_delay=60, name="evaluate_profiling_transcription"
)
def evaluate_profiling_transcription(self, profiling_run_id: str, transcript: str):
    """Evalua la transcripcion de la llamada contra las preguntas del QuestionSet."""
    from src.infrastructure.ai.prompts import PROFILING_EVALUATION_PROMPT
    from src.infrastructure.workers.tasks.parse_cv import _get_openai

    run_uuid = uuid.UUID(profiling_run_id)
    with _SyncSession() as db:
        try:
            profiling_run = db.get(ProfilingRun, run_uuid)
            if not profiling_run:
                return {"error": "ProfilingRun not found"}

            question_set = db.get(QuestionSet, profiling_run.question_set_id)
            if not question_set:
                return {"error": "QuestionSet not found"}
            questions = db.query(ProfilingQuestion).filter_by(question_set_id=question_set.id).all()
            questions_by_id = {str(q.id): q for q in questions}

            questions_data = [
                {
                    "id": str(q.id),
                    "text": q.text,
                    "is_critical": q.is_critical,
                    "expected_answer": q.expected_answer,
                    "positive_keywords": q.positive_keywords,
                    "risk_keywords": q.risk_keywords,
                }
                for q in questions
            ]

            from src.infrastructure.cache.redis_client import (
                get_active_ai_model_sync,
                get_active_ai_prompt_sync,
            )
            sys_prompt = get_active_ai_prompt_sync(db, "VOICE_PROFILING", PROFILING_EVALUATION_PROMPT)
            model = get_active_ai_model_sync(db, "OPENAI", "gpt-4o")

            prompt = (
                f"{sys_prompt}\n\n=== QUESTION SET ===\n"
                f"{json.dumps(questions_data, indent=2)}\n\n=== TRANSCRIPT ===\n{transcript}\n"
            )

            client = _get_openai()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            result_data = json.loads(response.choices[0].message.content or "{}")

            from src.infrastructure.db.models import CostLog, ProcessCandidate
            prompt_tokens = response.usage.prompt_tokens if getattr(response, 'usage', None) else 0
            completion_tokens = response.usage.completion_tokens if getattr(response, 'usage', None) else 0
            cost = (prompt_tokens * 0.005 / 1000) + (completion_tokens * 0.015 / 1000)
            cost_log = CostLog(
                process_id=db.query(ProcessCandidate).filter(ProcessCandidate.id == profiling_run.process_candidate_id).first().process_id,
                process_candidate_id=profiling_run.process_candidate_id,
                action="PROFILING_EVALUATION",
                provider="OPENAI",
                estimated_cost=cost,
                details={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
            )
            db.add(cost_log)

            answers = result_data.get("answers", [])
            for ans in answers:
                db.add(
                    ProfilingAnswer(
                        profiling_run_id=profiling_run.id,
                        question_id=uuid.UUID(ans["question_id"]),
                        transcription=ans.get("transcription_snippet"),
                        normalized_answer=ans.get("normalized_answer"),
                        evaluation_result=ans.get("evaluation_result"),
                        detected_keywords=ans.get("detected_keywords", []),
                        confidence_score=ans.get("confidence_score", 0.0),
                        requires_review=ans.get("requires_review", False),
                    )
                )

            # RB-006/RB-007 via el value object de dominio, en vez de que la IA
            # decida el nivel de avance directamente.
            failed_critical_count = 0
            total_weight = 0
            weighted_score = 0.0
            low_confidence = False
            for ans in answers:
                question = questions_by_id.get(ans.get("question_id"))
                if not question:
                    continue
                weight = question.weight
                total_weight += weight
                result = ans.get("evaluation_result")
                if result == "pass":
                    weighted_score += weight
                elif result == "neutral":
                    weighted_score += weight * 0.5
                if question.is_critical and result == "fail":
                    failed_critical_count += 1
                if ans.get("confidence_score", 1.0) < 0.5:
                    low_confidence = True

            total_weighted_score = (weighted_score / total_weight * 100) if total_weight else 0.0

            advancement = AdvancementProbabilityVO.from_scores(
                critical_questions_passed=failed_critical_count == 0,
                failed_critical_count=failed_critical_count,
                total_weighted_score=total_weighted_score,
                low_confidence_transcription=low_confidence,
                explanation=result_data.get("advancement_explanation", ""),
            )

            # ProfilingRun.status y la transicion de ProcessCandidate a PROFILING_COMPLETED
            # ya las aplico el webhook /elevenlabs/post-call-transcription al recibir la
            # transcripcion (ver src/api/v1/webhooks.py) — aqui solo calculamos el avance.
            profiling_run.advancement_probability = AdvancementProbability(advancement.level.value)
            profiling_run.advancement_explanation = advancement.explanation
            profiling_run.call_consent_status = result_data.get("verbal_consent", "ACCEPTED")

            db.commit()
            return {"status": "EVALUATED", "advancement_probability": advancement.level.value}

        except Exception as exc:
            db.rollback()
            logger.error(f"[profiling] error evaluando transcripcion: {exc}")
            raise self.retry(exc=exc, max_retries=settings.max_call_attempts)
