"""
Caso de uso de inicio de llamada de profiling (sincrono, pensado para Celery).

Reemplaza la logica que antes vivia directo en el worker: valida las reglas de
negocio (RB-003/005/010), transiciona el estado del candidato correctamente
(antes tenia un bug que rompia siempre esta transicion), crea el ProfilingRun
y dispara la llamada saliente real via Twilio.

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

from src.application.hiring_process.progress import sync_process_status_sync
from src.config import settings
from src.domain.candidate.state_machine import CandidateStateMachine
from src.domain.hiring_process.rules import HiringProcessRules
from src.domain.shared.exceptions import BusinessRuleException, NotFoundException
from src.infrastructure.db.models import (
    CandidateStatus,
    CostLog,
    HiringProcess,
    ProcessCandidate,
    ProfilingRun,
    ProfilingRunStatus,
    QuestionSet,
)
from src.infrastructure.voice.twilio_client import create_outbound_call

_ACTIVE_CALL_STATUSES = (ProfilingRunStatus.CALLING.value, ProfilingRunStatus.ANSWERED.value)


def _is_twilio_auth_error(exc: TwilioRestException) -> bool:
    return getattr(exc, "status", None) == 401 or getattr(exc, "code", None) == 20003


def _mark_candidate_profiling_failed(db: Session, pc: ProcessCandidate | None) -> None:
    if not pc or pc.status in {
        CandidateStatus.PROFILING_FAILED.value,
        CandidateStatus.PROFILING_COMPLETED.value,
        CandidateStatus.DISCARDED.value,
    }:
        return
    try:
        pc.status = CandidateStateMachine.transition(
            CandidateStatus(pc.status), CandidateStatus.PROFILING_FAILED
        ).value
    except BusinessRuleException:
        # Un run stale no debe bloquearse porque el candidato ya avanzó por otra
        # ruta (por ejemplo, un webhook tardío o una reparación anterior).
        return


class InitiateProfilingCallUseCase:
    def __init__(self, db: Session):
        self.db = db

    def execute(self, process_candidate_id: str) -> ProfilingRun:
        pc = self.db.get(ProcessCandidate, uuid.UUID(process_candidate_id))
        if not pc:
            raise NotFoundException("ProcessCandidate", process_candidate_id)

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

        pc.status = CandidateStateMachine.transition(
            CandidateStatus(pc.status), CandidateStatus.PROFILING_CALLING
        ).value

        profiling_run = ProfilingRun(
            process_candidate_id=pc.id,
            question_set_id=question_set.id,
            status=ProfilingRunStatus.CALLING.value,
            call_attempts=1,
            started_at=datetime.now(UTC),
        )
        self.db.add(profiling_run)
        self.db.flush()

        try:
            call_sid = create_outbound_call(candidate.phone, str(profiling_run.id))
        except TwilioRestException as exc:
            if not _is_twilio_auth_error(exc):
                raise
            profiling_run.status = ProfilingRunStatus.FAILED.value
            profiling_run.completed_at = datetime.now(UTC)
            profiling_run.twilio_status_detail = "twilio_auth_401"
            _mark_candidate_profiling_failed(self.db, pc)
            sync_process_status_sync(self.db, process.id)
            return profiling_run
        profiling_run.twilio_call_sid = call_sid
        sync_process_status_sync(self.db, process.id)

        return profiling_run


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
        run = self.db.get(ProfilingRun, uuid.UUID(profiling_run_id))
        if not run:
            raise NotFoundException("ProfilingRun", profiling_run_id)

        pc = self.db.get(ProcessCandidate, run.process_candidate_id)
        run.twilio_status_detail = reason[:30]

        if not allow_retry:
            run.status = ProfilingRunStatus.FAILED.value
            run.completed_at = datetime.now(UTC)
            _mark_candidate_profiling_failed(self.db, pc)
            if pc:
                sync_process_status_sync(self.db, pc.process_id)
            return run

        if run.call_attempts < settings.max_call_attempts:
            run.call_attempts += 1
            run.status = ProfilingRunStatus.CALLING.value
            candidate = pc.candidate if pc else None
            if not candidate or not candidate.phone:
                raise BusinessRuleException(
                    f"ProfilingRun {profiling_run_id}: candidato sin telefono, no se puede "
                    "reintentar."
                )
            try:
                run.twilio_call_sid = create_outbound_call(candidate.phone, str(run.id))
            except TwilioRestException as exc:
                if not _is_twilio_auth_error(exc):
                    raise
                run.status = ProfilingRunStatus.FAILED.value
                run.completed_at = datetime.now(UTC)
                run.twilio_status_detail = "twilio_auth_401"
                _mark_candidate_profiling_failed(self.db, pc)
            if pc:
                sync_process_status_sync(self.db, pc.process_id)
        else:
            run.status = ProfilingRunStatus.FAILED.value
            run.completed_at = datetime.now(UTC)
            _mark_candidate_profiling_failed(self.db, pc)
            if pc:
                sync_process_status_sync(self.db, pc.process_id)

        return run
