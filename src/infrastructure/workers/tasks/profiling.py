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
from src.infrastructure.ai.model_compat import DEFAULT_OPENAI_MODEL, chat_completion_options
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
def start_profiling_call(self, profiling_run_id: str):
    """Inicia una llamada saliente de profiling hacia el candidato (Twilio + ElevenLabs)."""
    with _SyncSession() as db:
        try:
            profiling_run = InitiateProfilingCallUseCase(db).execute(profiling_run_id)
            db.commit()
            return {
                "status": profiling_run.status,
                "profiling_run_id": str(profiling_run.id),
                "twilio_call_sid": profiling_run.twilio_call_sid,
            }
        except (BusinessRuleException, NotFoundException, DomainException) as exc:
            # Errores de negocio: no son transitorios, no tiene sentido reintentar.
            db.rollback()
            logger.warning(f"[profiling] no se inicio llamada para {profiling_run_id}: {exc}")
            return {"error": str(exc)}
        except Exception as exc:
            db.rollback()
            logger.error(f"[profiling] error transitorio iniciando llamada: {exc}")
            from src.infrastructure.cache.redis_client import get_global_setting_sync

            max_retries = int(
                get_global_setting_sync(db, "max_call_attempts", str(settings.max_call_attempts))
            )
            raise self.retry(exc=exc, max_retries=max_retries)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="retry_or_fail_profiling_call")
def retry_or_fail_profiling_call(self, profiling_run_id: str, reason: str):
    """Reintenta una llamada sin conectar, o marca PROFILING_FAILED si se agotaron los intentos."""
    with _SyncSession() as db:
        try:
            run = RetryOrFailProfilingCallUseCase(db).execute(profiling_run_id, reason)
            db.commit()
            if run.status == "QUEUED":
                start_profiling_call.delay(str(run.id))
            return {"status": run.status, "call_attempts": run.call_attempts}
        except (BusinessRuleException, NotFoundException, DomainException) as exc:
            db.rollback()
            logger.warning(f"[profiling] no se pudo reintentar {profiling_run_id}: {exc}")
            return {"error": str(exc)}
        except Exception as exc:
            db.rollback()
            logger.error(f"[profiling] error transitorio reintentando llamada: {exc}")
            from src.infrastructure.cache.redis_client import get_global_setting_sync

            max_retries = int(
                get_global_setting_sync(db, "max_call_attempts", str(settings.max_call_attempts))
            )
            raise self.retry(exc=exc, max_retries=max_retries)


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
                select(
                    ProfilingRun.id,
                    ProfilingRun.status,
                    ProfilingRun.started_at,
                    ProfilingRun.created_at,
                ).where(
                    ProfilingRun.status.in_(WATCHED_STATUSES)
                )
            ).all()

            processed = []
            for run_id, status, started_at, created_at in candidates:
                if not is_run_stale(
                    status,
                    started_at,
                    now,
                    calling_timeout,
                    answered_timeout,
                    created_at=created_at,
                ):
                    continue

                locked = db.execute(
                    select(ProfilingRun)
                    .where(ProfilingRun.id == run_id)
                    .with_for_update(skip_locked=True)
                ).scalar_one_or_none()
                if not locked:
                    continue  # otro worker lo tiene bloqueado ahora mismo (p.ej. un webhook)
                if not is_run_stale(
                    locked.status,
                    locked.started_at,
                    now,
                    calling_timeout,
                    answered_timeout,
                    created_at=locked.created_at,
                ):
                    continue  # se resolvio entre la lectura y el lock

                # Normaliza el dato histórico antes de cerrar la corrida. No publica tareas ni
                # repite llamadas: el watchdog siempre usa allow_retry=False.
                locked.started_at = locked.started_at or locked.created_at
                RetryOrFailProfilingCallUseCase(db).execute(
                    str(locked.id), "watchdog_timeout", allow_retry=False
                )
                processed.append(str(locked.id))

            db.commit()
            if processed:
                logger.warning(f"[watchdog] runs atascados procesados: {processed}")
            return {"processed": processed}
        except Exception as exc:
            db.rollback()
            logger.error(f"[watchdog] error revisando llamadas atascadas: {exc}")
            from src.infrastructure.cache.redis_client import get_global_setting_sync

            max_retries = int(
                get_global_setting_sync(db, "max_call_attempts", str(settings.max_call_attempts))
            )
            raise self.retry(exc=exc, max_retries=max_retries)


@shared_task(
    bind=True, max_retries=3, default_retry_delay=60, name="evaluate_profiling_transcription"
)
def evaluate_profiling_transcription(self, profiling_run_id: str, transcript: str):
    """Evalua la transcripcion de la llamada contra las preguntas del QuestionSet."""
    from src.infrastructure.workers.tasks.parse_cv import _get_openai

    run_uuid = uuid.UUID(profiling_run_id)
    with _SyncSession() as db:
        try:
            profiling_run = db.get(ProfilingRun, run_uuid)
            if not profiling_run:
                return {"error": "ProfilingRun not found"}
            pc = profiling_run.process_candidate
            if not pc:
                return {"error": "ProcessCandidate not found"}

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

            from src.application.ai.process_prompt_resolver import get_process_prompt_sync
            from src.infrastructure.cache.redis_client import get_active_ai_model_sync

            sys_prompt = get_process_prompt_sync(
                db, pc.process_id, "VOICE_PROFILING"
            ).system_prompt_text
            model = get_active_ai_model_sync(
                db, "VOICE_PROFILING", "OPENAI", DEFAULT_OPENAI_MODEL
            )

            prompt = (
                f"{sys_prompt}\n\n=== QUESTION SET ===\n"
                f"{json.dumps(questions_data, indent=2)}\n\n=== TRANSCRIPT ===\n{transcript}\n"
            )

            client = _get_openai()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                **chat_completion_options(model, temperature=0.2),
            )
            result_data = json.loads(response.choices[0].message.content or "{}")

            from src.infrastructure.costs import (
                calculate_openai_cost,
                extract_openai_usage,
                record_cost_sync,
            )
            from src.infrastructure.db.models import (
                HiringProcess,
                OperationType,
            )

            (
                prompt_tokens,
                completion_tokens,
                cached_tokens,
                cache_write_tokens,
                reasoning_tokens,
            ) = extract_openai_usage(response)
            evaluation_cost = calculate_openai_cost(
                model,
                prompt_tokens,
                completion_tokens,
                cached_tokens,
                cache_write_tokens,
                reasoning_tokens,
            )
            process = db.get(HiringProcess, pc.process_id) if pc else None
            with _SyncSession() as cost_db:
                record_cost_sync(
                    cost_db,
                    process_id=pc.process_id if pc else None,
                    candidate_id=pc.candidate_id if pc else None,
                    user_id=process.recruiter_id if process else None,
                    operation_type=OperationType.ANSWER_EVALUATION.value,
                    provider="OPENAI",
                    model_used=model,
                    tokens_input=prompt_tokens,
                    tokens_cached=cached_tokens,
                    tokens_output=completion_tokens,
                    estimated_cost=evaluation_cost.amount_usd,
                    cost_source=evaluation_cost.source,
                    external_reference=f"openai:{response.id}",
                    cost_breakdown=evaluation_cost.breakdown,
                )
                cost_db.commit()

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

            from src.application.notifications.service import (
                check_and_notify_budget_sync,
                create_notification_sync,
            )

            if pc:
                create_notification_sync(
                    db,
                    title="Profiling completado",
                    description=(
                        "Se completó la evaluación de profiling por voz "
                        "para un candidato en el proceso."
                    ),
                    category="PROFILING_COMPLETED",
                    type="SUCCESS",
                    process_id=pc.process_id,
                    link="/app/profiling",
                )
                check_and_notify_budget_sync(db, pc.process_id)

            db.commit()
            return {"status": "EVALUATED", "advancement_probability": advancement.level.value}

        except Exception as exc:
            db.rollback()
            logger.error(f"[profiling] error evaluando transcripcion: {exc}")
            from src.infrastructure.cache.redis_client import get_global_setting_sync

            max_retries = int(
                get_global_setting_sync(db, "max_call_attempts", str(settings.max_call_attempts))
            )
            raise self.retry(exc=exc, max_retries=max_retries)
