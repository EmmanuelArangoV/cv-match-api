"""
Caso de uso de inicio de llamada de profiling (sincrono, pensado para Celery).

La corrida ya fue persistida por el trigger. El worker recibe ``run_id``,
la bloquea y solo publica la llamada si sigue en QUEUED.

La configuracion de voz (system prompt/idioma/voz) se resuelve mas tarde, en el
webhook `/twilio/twiml` (una vez Twilio confirma que un humano contesto) en vez
de aqui, para no tener que cachear nada entre el disparo de la llamada y ese
momento — se vuelve a leer QuestionSet/HiringProcess por `run_id`, que ya viaja
en la URL del webhook.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from twilio.base.exceptions import TwilioRestException

from src.application.profiling.call_context_cache import (
    build_dynamic_variables,
    cache_call_context_sync,
)
from src.application.profiling.lifecycle import transition_profiling_sync
from src.application.profiling.voice_config_resolver import resolve_voice_config
from src.config import settings
from src.domain.hiring_process.rules import HiringProcessRules
from src.domain.shared.exceptions import BusinessRuleException, NotFoundException
from src.infrastructure.db.models import (
    CostLog,
    HiringProcess,
    ProcessCandidate,
    ProfilingRun,
    ProfilingRunStatus,
    QuestionSet,
)
from src.infrastructure.voice import elevenlabs_client
from src.infrastructure.voice.twilio_client import create_outbound_call

_ACTIVE_CALL_STATUSES = (ProfilingRunStatus.CALLING.value, ProfilingRunStatus.ANSWERED.value)


def _is_twilio_auth_error(exc: TwilioRestException) -> bool:
    return getattr(exc, "status", None) == 401 or getattr(exc, "code", None) == 20003


class InitiateProfilingCallUseCase:
    def __init__(self, db: Session):
        self.db = db

    def execute(self, profiling_run_id: str) -> ProfilingRun:
        run = self.db.execute(
            select(ProfilingRun)
            .where(ProfilingRun.id == uuid.UUID(profiling_run_id))
            .with_for_update()
        ).scalar_one_or_none()
        if not run:
            raise NotFoundException("ProfilingRun", profiling_run_id)
        if run.status != ProfilingRunStatus.QUEUED.value:
            # Entrega duplicada o callback tardio: no publica otra llamada.
            return run

        pc = self.db.get(ProcessCandidate, run.process_candidate_id)
        if not pc:
            raise NotFoundException("ProcessCandidate", str(run.process_candidate_id))

        process = self.db.get(HiringProcess, pc.process_id)
        if not process:
            raise NotFoundException("HiringProcess", str(pc.process_id))

        HiringProcessRules.require_question_set_for_profiling(process.question_set_id)
        question_set = self.db.get(QuestionSet, process.question_set_id)
        if not question_set:
            raise NotFoundException("QuestionSet", str(process.question_set_id))

        candidate = pc.candidate
        if not candidate.phone:
            raise BusinessRuleException(
                f"El candidato {candidate.id} no tiene telefono registrado, no se puede llamar."
            )

        active_calls = self.db.execute(
            select(func.count(ProfilingRun.id)).where(
                ProfilingRun.status.in_(_ACTIVE_CALL_STATUSES)
            )
        ).scalar_one()
        HiringProcessRules.enforce_max_concurrent_calls(active_calls, settings.max_concurrent_calls)

        spent_usd = self.db.execute(
            select(func.coalesce(func.sum(CostLog.estimated_cost), 0)).where(
                CostLog.process_id == process.id
            )
        ).scalar_one()
        HiringProcessRules.require_budget_available(float(spent_usd), float(process.budget_max_usd))

        # Preparar todo el contexto antes de marcar. El webhook de Twilio solo
        # debe actualizar estado y devolver el TwiML de ElevenLabs.
        from src.infrastructure.ai.prompts import VOICE_CALL_AGENT_BASE_PROMPT
        from src.infrastructure.cache.redis_client import get_active_ai_prompt_sync

        universal_prompt = get_active_ai_prompt_sync(
            self.db, "VOICE_CALL_AGENT", VOICE_CALL_AGENT_BASE_PROMPT
        )
        voice_config = resolve_voice_config(
            question_set, process, pc.whatsapp_consent_status, universal_prompt
        )
        dynamic_variables = build_dynamic_variables(
            f"{candidate.name} {candidate.last_name}".strip(),
            process.job_title,
            str(process.id),
        )
        cache_call_context_sync(
            str(run.id), voice_config, dynamic_variables, candidate.phone
        )
        # Esta consulta externa ocurre antes de marcar, no durante el saludo.
        elevenlabs_client.preload_agent_overrides(voice_config.agent_id)

        transition_profiling_sync(
            self.db, run, pc, ProfilingRunStatus.CALLING, now=datetime.now(UTC)
        )
        run.call_attempts += 1
        self.db.flush()

        try:
            call_sid = create_outbound_call(candidate.phone, str(run.id))
        except TwilioRestException as exc:
            if not _is_twilio_auth_error(exc):
                raise
            transition_profiling_sync(
                self.db,
                run,
                pc,
                ProfilingRunStatus.FAILED,
                detail="twilio_auth_401",
            )
            return run
        run.twilio_call_sid = call_sid
        return run


class RetryOrFailProfilingCallUseCase:
    """
    Se dispara cuando AMD detecta buzon de voz (o Twilio reporta que la llamada
    nunca conecto: no-answer/busy/failed/canceled). Reintenta hasta
    settings.max_call_attempts; agotados los intentos, marca PROFILING_FAILED
    (RB-008: nunca DISCARDED automatico, solo el recruiter puede revertir).
    """

    def __init__(self, db: Session):
        self.db = db

    def execute(
        self,
        profiling_run_id: str,
        reason: str,
        allow_retry: bool = True,
    ) -> ProfilingRun:
        run = self.db.execute(
            select(ProfilingRun)
            .where(ProfilingRun.id == uuid.UUID(profiling_run_id))
            .with_for_update()
        ).scalar_one_or_none()
        if not run:
            raise NotFoundException("ProfilingRun", profiling_run_id)

        pc = self.db.get(ProcessCandidate, run.process_candidate_id)
        if not pc:
            raise NotFoundException("ProcessCandidate", str(run.process_candidate_id))
        if run.status in {
            ProfilingRunStatus.COMPLETED.value,
            ProfilingRunStatus.FAILED.value,
            ProfilingRunStatus.NO_ANSWER.value,
            ProfilingRunStatus.VOICEMAIL_DETECTED.value,
            ProfilingRunStatus.CANCELLED.value,
        }:
            return run

        if not allow_retry:
            transition_profiling_sync(self.db, run, pc, ProfilingRunStatus.FAILED, detail=reason)
            return run

        if run.call_attempts < settings.max_call_attempts:
            transition_profiling_sync(
                self.db, run, pc, ProfilingRunStatus.RETRY_PENDING, detail=reason
            )
            transition_profiling_sync(self.db, run, pc, ProfilingRunStatus.QUEUED, detail=reason)
        else:
            if reason.startswith("AMD:"):
                target = ProfilingRunStatus.VOICEMAIL_DETECTED
            elif reason.startswith("status:no-answer"):
                target = ProfilingRunStatus.NO_ANSWER
            else:
                target = ProfilingRunStatus.FAILED
            transition_profiling_sync(self.db, run, pc, target, detail=reason)

        return run
