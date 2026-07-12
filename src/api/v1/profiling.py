import asyncio
import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import RequireRecruiter, get_current_user
from src.config import settings
from src.domain.candidate.state_machine import CandidateStateMachine
from src.domain.hiring_process.rules import HiringProcessRules
from src.domain.shared.exceptions import BusinessRuleException, NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    CandidateStatus,
    HiringProcess,
    ProcessCandidate,
    ProcessStatus,
    ProfilingRun,
    User,
    UserRole,
    WhatsAppConsentStatus,
)
from src.infrastructure.db.repositories.candidate_repository import CandidateRepository

router = APIRouter(prefix="/processes", tags=["Profiling"])
global_router = APIRouter(prefix="/profiling", tags=["Profiling"])


class TriggerProfilingRequest(BaseModel):
    process_candidate_ids: list[uuid.UUID]


def _candidate_name(run: ProfilingRun) -> str:
    candidate = run.process_candidate.candidate
    return f"{candidate.name} {candidate.last_name}"


def _serialize_run(run: ProfilingRun, candidate_name: str) -> dict:
    return {
        "id": str(run.id),
        "process_candidate_id": str(run.process_candidate_id),
        "candidate_id": str(run.process_candidate.candidate_id),
        "candidate_name": candidate_name,
        "question_set_id": str(run.question_set_id),
        "status": run.status,
        "call_attempts": run.call_attempts,
        "advancement_probability": run.advancement_probability,
        "advancement_explanation": run.advancement_explanation,
        "transcription_url": run.transcription_url,
        "transcript_summary": run.transcript_summary,
        "transcript_turns": run.transcript_turns,
        "has_audio": run.elevenlabs_conversation_id is not None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


@router.post("/{process_id}/profiling/trigger")
async def trigger_profiling(
    process_id: uuid.UUID,
    body: TriggerProfilingRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dispara profiling manual (RB-004) para los candidatos MATCHED seleccionados."""
    from src.infrastructure.workers.tasks.profiling import start_profiling_call
    from src.infrastructure.workers.tasks.whatsapp import send_whatsapp_consent

    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    HiringProcessRules.require_active_process(ProcessStatus(process.status))
    HiringProcessRules.require_manual_candidate_selection(body.process_candidate_ids)
    HiringProcessRules.require_question_set_for_profiling(process.question_set_id)

    repo = CandidateRepository(db)
    queued: list[ProcessCandidate] = []
    skipped: list[dict] = []

    for pc_id in body.process_candidate_ids:
        pc = await repo.find_process_candidate_by_id(pc_id)
        if not pc or pc.process_id != process_id:
            skipped.append(
                {
                    "process_candidate_id": str(pc_id),
                    "reason": "No encontrado en este proceso",
                }
            )
            continue
        if pc.status == CandidateStatus.MATCHED.value:
            pc.status = CandidateStateMachine.transition(
                CandidateStatus(pc.status), CandidateStatus.SELECTED_FOR_PROFILING
            ).value
            pc.status = CandidateStateMachine.transition(
                CandidateStatus(pc.status), CandidateStatus.PROFILING_QUEUED
            ).value
        elif pc.status == CandidateStatus.PROFILING_FAILED.value:
            # Reintento manual: la maquina de estados ya permite este salto directo.
            pc.status = CandidateStateMachine.transition(
                CandidateStatus(pc.status), CandidateStatus.PROFILING_QUEUED
            ).value
        else:
            skipped.append(
                {
                    "process_candidate_id": str(pc_id),
                    "reason": (
                        f"Estado actual '{pc.status}' no es elegible "
                        "(se requiere MATCHED o PROFILING_FAILED)"
                    ),
                }
            )
            continue

        queued.append(pc)

    await db.commit()

    whatsapp_configured = bool(
        settings.meta_whatsapp_access_token and settings.meta_whatsapp_phone_number_id
    )

    tasks = []
    for pc in queued:
        already_accepted = pc.whatsapp_consent_status == WhatsAppConsentStatus.ACCEPTED.value
        if already_accepted or not whatsapp_configured:
            # Ya dio consentimiento en una activacion anterior (reintento), o no hay
            # WhatsApp configurado para pedirlo — llamar directo, sin esperar nada.
            task = start_profiling_call.delay(str(pc.id))
            tasks.append({"process_candidate_id": str(pc.id), "task_id": task.id})
        else:
            # Pide consentimiento por WhatsApp; la llamada la dispara _apply_intent al
            # aceptar, o resolve_whatsapp_timeouts si no responde a tiempo.
            send_whatsapp_consent.delay(str(pc.id))
            tasks.append({"process_candidate_id": str(pc.id), "task_id": ""})

    return {
        "process_id": str(process_id),
        "queued": len(tasks),
        "tasks": tasks,
        "skipped": skipped,
    }


@router.get("/{process_id}/profiling/runs")
async def list_profiling_runs(
    process_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(ProfilingRun)
        .join(ProcessCandidate, ProfilingRun.process_candidate_id == ProcessCandidate.id)
        .where(ProcessCandidate.process_id == process_id)
        .options(
            selectinload(ProfilingRun.process_candidate).selectinload(ProcessCandidate.candidate)
        )
        .order_by(ProfilingRun.created_at.desc())
    )
    runs = list(result.scalars().all())

    return {
        "total": len(runs),
        "profiling_runs": [_serialize_run(run, _candidate_name(run)) for run in runs],
    }


@global_router.get("/runs")
async def list_all_profiling_runs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Listado global de ProfilingRun para la vista /profiling (todas las prospecciones activas)."""
    query = (
        select(ProfilingRun)
        .join(ProcessCandidate, ProfilingRun.process_candidate_id == ProcessCandidate.id)
        .options(
            selectinload(ProfilingRun.process_candidate).selectinload(ProcessCandidate.candidate)
        )
        .order_by(ProfilingRun.created_at.desc())
    )

    if current_user.role == UserRole.RECRUITER.value:
        query = query.join(HiringProcess, ProcessCandidate.process_id == HiringProcess.id).where(
            HiringProcess.recruiter_id == current_user.id
        )

    result = await db.execute(query)
    runs = list(result.scalars().all())

    return {
        "total": len(runs),
        "profiling_runs": [_serialize_run(run, _candidate_name(run)) for run in runs],
    }


from src.infrastructure.db.models import (
    ProfilingAnswer,
    ProfilingQuestion,
    ProfilingRunStatus,
)


class OverrideProfilingRequest(BaseModel):
    advancement_probability: str
    advancement_explanation: str


@global_router.get("/runs/{run_id}")
async def get_profiling_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(ProfilingRun)
        .where(ProfilingRun.id == run_id)
        .options(
            selectinload(ProfilingRun.process_candidate).selectinload(ProcessCandidate.candidate)
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundException("ProfilingRun no encontrado")
    return _serialize_run(run, _candidate_name(run))


@global_router.get("/runs/{run_id}/audio")
async def get_profiling_run_audio(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Proxea el audio de la llamada directo desde la API de ElevenLabs usando el
    elevenlabs_conversation_id ya guardado — no lo persistimos nosotros, se pide
    en vivo cada vez (mas simple que subirlo a R2 aparte).
    """
    from src.infrastructure.voice.elevenlabs_client import get_elevenlabs_client

    run = await db.get(ProfilingRun, run_id)
    if not run:
        raise NotFoundException("ProfilingRun no encontrado")
    if not run.elevenlabs_conversation_id:
        raise NotFoundException("Esta llamada no tiene conversacion de ElevenLabs asociada")

    def _fetch_audio() -> bytes:
        client = get_elevenlabs_client()
        chunks = client.conversational_ai.conversations.audio.get(run.elevenlabs_conversation_id)
        return b"".join(chunks)

    try:
        audio_bytes = await asyncio.to_thread(_fetch_audio)
    except Exception as exc:
        raise BusinessRuleException(f"No se pudo obtener el audio de ElevenLabs: {exc}") from exc

    return Response(content=audio_bytes, media_type="audio/mpeg")


@global_router.get("/runs/{run_id}/answers")
async def get_profiling_answers(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(ProfilingAnswer, ProfilingQuestion)
        .join(ProfilingQuestion, ProfilingAnswer.question_id == ProfilingQuestion.id)
        .where(ProfilingAnswer.profiling_run_id == run_id)
        .order_by(ProfilingQuestion.order_index.asc())
    )
    rows = result.all()

    answers = []
    for ans, question in rows:
        answers.append(
            {
                "id": str(ans.id),
                "question": {
                    "id": str(question.id),
                    "text": question.text,
                    "weight": question.weight,
                    "is_critical": question.is_critical,
                },
                "transcription": ans.transcription,
                "normalized_answer": ans.normalized_answer,
                "evaluation_result": ans.evaluation_result,
                "confidence_score": float(ans.confidence_score) if ans.confidence_score else None,
                "requires_review": ans.requires_review,
            }
        )
    return {"answers": answers}


@global_router.post("/runs/{run_id}/cancel")
async def cancel_profiling_run(
    run_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(ProfilingRun)
        .where(ProfilingRun.id == run_id)
        .options(selectinload(ProfilingRun.process_candidate))
    )
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundException("ProfilingRun no encontrado")

    if run.status != ProfilingRunStatus.QUEUED.value:
        raise BusinessRuleException("Solo se pueden cancelar llamadas en estado QUEUED")

    run.status = ProfilingRunStatus.FAILED.value
    pc = run.process_candidate
    if pc:
        pc.status = CandidateStateMachine.transition(
            CandidateStatus(pc.status), CandidateStatus.PROFILING_FAILED
        ).value

    await db.commit()
    return {"message": "Llamada cancelada correctamente"}


@global_router.patch("/runs/{run_id}/override")
async def override_profiling_run(
    run_id: uuid.UUID,
    body: OverrideProfilingRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(ProfilingRun)
        .where(ProfilingRun.id == run_id)
        .options(
            selectinload(ProfilingRun.process_candidate).selectinload(ProcessCandidate.candidate)
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundException("ProfilingRun no encontrado")

    if (
        run.status != ProfilingRunStatus.EVALUATED.value
        and run.status != ProfilingRunStatus.COMPLETED.value
    ):
        raise BusinessRuleException("Solo se puede sobrescribir una llamada evaluada o completada")

    run.advancement_probability = body.advancement_probability
    run.advancement_explanation = body.advancement_explanation

    from src.infrastructure.db.audit import record_audit
    record_audit(db, current_user.id, "MANUAL_OVERRIDE", "ProfilingRun", run.id)
    await db.commit()
    await db.refresh(run)
    return _serialize_run(run, _candidate_name(run))
