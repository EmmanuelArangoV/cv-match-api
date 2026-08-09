"""Fuente única para el progreso operativo de un proceso.

Los estados técnicos siguen viviendo en ``ProcessCandidate`` y ``ProfilingRun``.
Este módulo es la única pieza autorizada para proyectarlos al estado agregado del
proceso y a los contadores que consume el frontend.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.config import settings
from src.domain.profiling.watchdog import is_run_stale
from src.infrastructure.db.models import (
    CandidateStatus,
    HiringProcess,
    JobDescription,
    ProcessCandidate,
    ProcessStatus,
    ProfilingRun,
    ProfilingRunStatus,
)

BOARD_COLUMN_CV_MATCH = "CV_MATCH"
BOARD_COLUMN_QUEUED = "QUEUED"
BOARD_COLUMN_CALLING = "CALLING"
BOARD_COLUMN_COMPLETED = "COMPLETED"
BOARD_COLUMN_FAILED = "FAILED"

BOARD_COLUMNS = (
    BOARD_COLUMN_CV_MATCH,
    BOARD_COLUMN_QUEUED,
    BOARD_COLUMN_CALLING,
    BOARD_COLUMN_COMPLETED,
    BOARD_COLUMN_FAILED,
)

PROCESS_STAGE_LABELS = {
    "DRAFT": "Borrador",
    "CVS_UPLOADED": "CVs cargados",
    "CVS_PROCESSED": "CVs procesados",
    "CV_PROCESSING": "Procesando CVs",
    "CV_ERROR": "CVs con errores",
    "MATCH_PROCESSING": "Procesando match",
    "MATCH_DONE": "Match realizado",
    "PROFILING_CONFIGURED": "Profiling configurado",
    "PROFILING_ACTIVE": "Profiling activo",
    "PROFILING_COMPLETED": "Profiling completado",
    "CLOSED": "Cerrado",
    "ARCHIVED": "Archivado",
}

_ADMIN_STATUSES = {ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value}
_CV_PENDING_STATUSES = {
    CandidateStatus.LOADED.value,
    CandidateStatus.CV_PROCESSING.value,
}
_CV_ERROR_STATUSES = {CandidateStatus.CV_ERROR.value}
_MATCH_PENDING_STATUSES = {
    CandidateStatus.MATCH_PENDING.value,
}
_MATCH_ACTIVE_STATUSES = {CandidateStatus.MATCH_PROCESSING.value}
_MATCHED_STATUSES = {
    CandidateStatus.MATCHED.value,
    CandidateStatus.SELECTED_FOR_PROFILING.value,
    CandidateStatus.PROFILING_QUEUED.value,
    CandidateStatus.PROFILING_CALLING.value,
    CandidateStatus.PROFILING_COMPLETED.value,
    CandidateStatus.PROFILING_FAILED.value,
}
_PROFILING_ACTIVE_CANDIDATE_STATUSES = {
    CandidateStatus.SELECTED_FOR_PROFILING.value,
    CandidateStatus.PROFILING_QUEUED.value,
    CandidateStatus.PROFILING_CALLING.value,
}
_PROFILING_TERMINAL_CANDIDATE_STATUSES = {
    CandidateStatus.PROFILING_COMPLETED.value,
    CandidateStatus.PROFILING_FAILED.value,
}
_ACTIVE_RUN_STATUSES = {
    ProfilingRunStatus.PENDING.value,
    ProfilingRunStatus.QUEUED.value,
    ProfilingRunStatus.CALLING.value,
    ProfilingRunStatus.ANSWERED.value,
    ProfilingRunStatus.RETRY_PENDING.value,
}
_TERMINAL_RUN_STATUSES = {
    ProfilingRunStatus.NO_ANSWER.value,
    ProfilingRunStatus.FAILED.value,
    ProfilingRunStatus.COMPLETED.value,
    ProfilingRunStatus.CANCELLED.value,
    ProfilingRunStatus.VOICEMAIL_DETECTED.value,
}


@dataclass(frozen=True)
class ProcessProgress:
    process_id: str
    process_status: str
    stage: str
    stage_label: str
    updated_at: datetime
    counts: dict[str, int]
    active_calls: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "process_id": self.process_id,
            "process_status": self.process_status,
            "stage": self.stage,
            "stage_label": self.stage_label,
            "updated_at": self.updated_at.isoformat(),
            "counts": self.counts,
            "active_calls": self.active_calls,
        }


@dataclass(frozen=True)
class CandidatePipelineProjection:
    process_candidate: ProcessCandidate
    latest_run: ProfilingRun | None
    board_column: str
    state_label: str
    consistency: str
    consistency_explanation: str | None
    effective_updated_at: datetime
    run_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        pc = self.process_candidate
        candidate = getattr(pc, "candidate", None)
        process = getattr(pc, "process", None)
        recruiter = getattr(process, "recruiter", None) if process else None
        run = self.latest_run
        return {
            "process_candidate_id": str(pc.id),
            "candidate_id": str(pc.candidate_id),
            "candidate_name": (
                f"{candidate.name} {candidate.last_name}".strip() if candidate else "Candidato"
            ),
            "candidate_email": candidate.email if candidate else None,
            "board_column": self.board_column,
            "state_label": self.state_label,
            "candidate_status": str(pc.status),
            "whatsapp_consent_status": pc.effective_whatsapp_consent_status,
            "latest_run": (
                {
                    "id": str(run.id),
                    "status": str(run.status),
                    "call_attempts": run.call_attempts,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                    "created_at": run.created_at.isoformat(),
                    "updated_at": run.updated_at.isoformat(),
                    "advancement_probability": run.advancement_probability,
                    "twilio_status_detail": run.twilio_status_detail,
                }
                if run
                else None
            ),
            "run_count": self.run_count,
            "process": (
                {
                    "id": str(process.id),
                    "name": process.name,
                    "job_title": process.job_title,
                }
                if process
                else None
            ),
            "recruiter": (
                {
                    "id": str(recruiter.id),
                    "name": f"{recruiter.name} {recruiter.last_name}".strip(),
                }
                if recruiter
                else None
            ),
            "effective_updated_at": self.effective_updated_at.isoformat(),
            "consistency": self.consistency,
            "consistency_explanation": self.consistency_explanation,
        }


_CANDIDATE_STATE_LABELS = {
    CandidateStatus.LOADED.value: "CV cargado",
    CandidateStatus.CV_PROCESSING.value: "Procesando CV",
    CandidateStatus.CV_ERROR.value: "Error al procesar CV",
    CandidateStatus.MATCH_PENDING.value: "Match pendiente",
    CandidateStatus.MATCH_PROCESSING.value: "Procesando match",
    CandidateStatus.MATCHED.value: "Match completado",
    CandidateStatus.SELECTED_FOR_PROFILING.value: "Esperando consentimiento",
    CandidateStatus.PROFILING_QUEUED.value: "En cola",
    CandidateStatus.PROFILING_CALLING.value: "Llamando",
    CandidateStatus.PROFILING_COMPLETED.value: "Completada",
    CandidateStatus.PROFILING_FAILED.value: "Fallida",
    CandidateStatus.DISCARDED.value: "Descartado",
}

_RUN_PRESENTATION = {
    ProfilingRunStatus.PENDING.value: (BOARD_COLUMN_QUEUED, "Esperando consentimiento"),
    ProfilingRunStatus.QUEUED.value: (BOARD_COLUMN_QUEUED, "En cola"),
    ProfilingRunStatus.RETRY_PENDING.value: (BOARD_COLUMN_QUEUED, "Reintento pendiente"),
    ProfilingRunStatus.CALLING.value: (BOARD_COLUMN_CALLING, "Llamando"),
    ProfilingRunStatus.ANSWERED.value: (BOARD_COLUMN_CALLING, "Contestada"),
    ProfilingRunStatus.COMPLETED.value: (BOARD_COLUMN_COMPLETED, "Completada"),
    ProfilingRunStatus.NO_ANSWER.value: (BOARD_COLUMN_FAILED, "Sin respuesta"),
    ProfilingRunStatus.VOICEMAIL_DETECTED.value: (BOARD_COLUMN_FAILED, "Buzon de voz"),
    ProfilingRunStatus.CANCELLED.value: (BOARD_COLUMN_FAILED, "Cancelada"),
    ProfilingRunStatus.FAILED.value: (BOARD_COLUMN_FAILED, "Fallida"),
}

_CANDIDATE_ACTIVE_INTENT = {
    CandidateStatus.SELECTED_FOR_PROFILING.value,
    CandidateStatus.PROFILING_QUEUED.value,
    CandidateStatus.PROFILING_CALLING.value,
}


def _candidate_column(status: str) -> str:
    if status in {
        CandidateStatus.SELECTED_FOR_PROFILING.value,
        CandidateStatus.PROFILING_QUEUED.value,
    }:
        return BOARD_COLUMN_QUEUED
    if status == CandidateStatus.PROFILING_CALLING.value:
        return BOARD_COLUMN_CALLING
    if status == CandidateStatus.PROFILING_COMPLETED.value:
        return BOARD_COLUMN_COMPLETED
    if status == CandidateStatus.PROFILING_FAILED.value:
        return BOARD_COLUMN_FAILED
    return BOARD_COLUMN_CV_MATCH


def build_candidate_projection(
    pc: ProcessCandidate,
    latest_run: ProfilingRun | None,
) -> CandidatePipelineProjection:
    """Resuelve una tarjeta sin ocultar contradicciones historicas."""

    candidate_status = str(pc.status)
    pc_updated_at = pc.updated_at or pc.created_at
    if latest_run is None:
        column = _candidate_column(candidate_status)
        attention = column != BOARD_COLUMN_CV_MATCH
        explanation = None
        if attention:
            explanation = "El candidato esta en profiling, pero no existe una corrida asociada."
        return CandidatePipelineProjection(
            process_candidate=pc,
            latest_run=None,
            board_column=column,
            state_label=_CANDIDATE_STATE_LABELS.get(candidate_status, candidate_status),
            consistency="ATTENTION" if attention else "OK",
            consistency_explanation=explanation,
            effective_updated_at=pc_updated_at,
            run_count=0,
        )

    run_status = str(latest_run.status)
    run_updated_at = latest_run.updated_at or latest_run.created_at
    column, label = _RUN_PRESENTATION[run_status]
    consistency = "OK"
    explanation = None

    # Una accion humana posterior a un intento terminal prevalece visualmente,
    # pero nunca origina otra llamada por si sola.
    if (
        run_status in _TERMINAL_RUN_STATUSES
        and candidate_status in _CANDIDATE_ACTIVE_INTENT
        and pc_updated_at > run_updated_at
    ):
        column = _candidate_column(candidate_status)
        label = _CANDIDATE_STATE_LABELS.get(candidate_status, candidate_status)
        consistency = "ATTENTION"
        explanation = "Ultimo intento fallido; sin corrida activa. Reintento manual requerido."
    else:
        expected_columns = {
            BOARD_COLUMN_QUEUED: {BOARD_COLUMN_QUEUED},
            BOARD_COLUMN_CALLING: {BOARD_COLUMN_CALLING},
            BOARD_COLUMN_COMPLETED: {BOARD_COLUMN_COMPLETED},
            BOARD_COLUMN_FAILED: {BOARD_COLUMN_FAILED, BOARD_COLUMN_QUEUED},
        }
        candidate_column = _candidate_column(candidate_status)
        if column != BOARD_COLUMN_CV_MATCH and candidate_column not in expected_columns[column]:
            consistency = "ATTENTION"
            explanation = (
                f"La corrida esta en {run_status}, pero el candidato permanece en "
                f"{candidate_status}."
            )

    return CandidatePipelineProjection(
        process_candidate=pc,
        latest_run=latest_run,
        board_column=column,
        state_label=label,
        consistency=consistency,
        consistency_explanation=explanation,
        effective_updated_at=max(pc_updated_at, run_updated_at),
        run_count=1,
    )


def build_candidate_projections(
    candidates: Iterable[ProcessCandidate], runs: Iterable[ProfilingRun]
) -> list[CandidatePipelineProjection]:
    run_list = list(runs)
    latest_by_candidate: dict[str, ProfilingRun] = {}
    for run in run_list:
        key = str(run.process_candidate_id)
        current = latest_by_candidate.get(key)
        if current is None or (run.created_at, str(run.id)) > (current.created_at, str(current.id)):
            latest_by_candidate[key] = run
    run_counts: dict[str, int] = {}
    for run in run_list:
        key = str(run.process_candidate_id)
        run_counts[key] = run_counts.get(key, 0) + 1
    projections = []
    for pc in candidates:
        projection = build_candidate_projection(pc, latest_by_candidate.get(str(pc.id)))
        projections.append(replace(projection, run_count=run_counts.get(str(pc.id), 0)))
    return projections


def _value(item: Any, field: str) -> Any:
    return getattr(item, field, item)


def derive_process_stage(
    process_status: str,
    has_job_description: bool,
    has_question_set: bool,
    candidate_statuses: Iterable[str],
    run_statuses: Iterable[str],
) -> str:
    """Deriva la etapa visible sin mutar el estado administrativo del proceso."""

    if process_status in _ADMIN_STATUSES:
        return process_status

    statuses = list(candidate_statuses)
    runs = list(run_statuses)
    # La ausencia de JD bloquea nuevas operaciones, pero no debe borrar el
    # resultado histórico de candidatos que ya fueron procesados.
    if not statuses:
        return ProcessStatus.DRAFT.value
    # LOADED significa que el recruiter aún no ha pulsado "Analizar CVs";
    # solo CV_PROCESSING debe mostrarse como trabajo activo.
    if any(status == CandidateStatus.CV_PROCESSING.value for status in statuses):
        return "CV_PROCESSING"
    if any(status == CandidateStatus.CV_ERROR.value for status in statuses):
        return "CV_ERROR"
    if any(status == CandidateStatus.LOADED.value for status in statuses):
        return ProcessStatus.CVS_UPLOADED.value
    if any(status in _MATCH_ACTIVE_STATUSES for status in statuses):
        return ProcessStatus.MATCH_PROCESSING.value

    matched = any(status in _MATCHED_STATUSES for status in statuses)
    profiling_active = any(status in _PROFILING_ACTIVE_CANDIDATE_STATUSES for status in statuses)
    profiling_has_terminal = any(
        status in _PROFILING_TERMINAL_CANDIDATE_STATUSES for status in statuses
    ) or any(status in _TERMINAL_RUN_STATUSES for status in runs)

    if has_question_set and profiling_active:
        return ProcessStatus.PROFILING_ACTIVE.value
    if has_question_set and matched and profiling_has_terminal:
        return ProcessStatus.PROFILING_COMPLETED.value
    if has_question_set and matched:
        return ProcessStatus.PROFILING_CONFIGURED.value
    if matched:
        return ProcessStatus.MATCH_DONE.value
    return "CVS_PROCESSED"


def derive_persisted_process_status(
    current_status: str,
    stage: str,
) -> str:
    """Mapea la etapa detallada al enum persistido, respetando cierres manuales."""

    if current_status in _ADMIN_STATUSES:
        return current_status
    return (
        ProcessStatus.CVS_UPLOADED.value
        if stage in {"CV_PROCESSING", "CV_ERROR", "CVS_PROCESSED"}
        else stage
    )


def _candidate_counts(statuses: list[str]) -> dict[str, int]:
    total = len(statuses)
    cv_pending = sum(status in _CV_PENDING_STATUSES for status in statuses)
    cv_errors = sum(status in _CV_ERROR_STATUSES for status in statuses)
    cv_processed = total - cv_pending - cv_errors
    match_pending = sum(status in _MATCH_PENDING_STATUSES for status in statuses)
    match_processing = sum(status == CandidateStatus.MATCH_PROCESSING.value for status in statuses)
    matched = sum(status in _MATCHED_STATUSES for status in statuses)
    profiling_queued = sum(status == CandidateStatus.PROFILING_QUEUED.value for status in statuses)
    profiling_active = sum(status in _PROFILING_ACTIVE_CANDIDATE_STATUSES for status in statuses)
    profiling_completed = sum(
        status == CandidateStatus.PROFILING_COMPLETED.value for status in statuses
    )
    profiling_failed = sum(status == CandidateStatus.PROFILING_FAILED.value for status in statuses)

    return {
        "total_cvs": total,
        "cv_pending": cv_pending,
        "cv_processing": sum(status == CandidateStatus.CV_PROCESSING.value for status in statuses),
        "cv_processed": cv_processed,
        "cv_errors": cv_errors,
        "match_pending": match_pending,
        "match_processing": match_processing,
        "matched": matched,
        "profiling_queued": profiling_queued,
        "profiling_active": profiling_active,
        "profiling_completed": profiling_completed,
        "profiling_failed": profiling_failed,
    }


def _active_call_payload(run: ProfilingRun, candidate_status: str, now: datetime) -> dict[str, Any]:
    started_at = run.started_at or run.created_at
    elapsed_seconds = max(0, int((now - started_at).total_seconds())) if started_at else 0
    return {
        "run_id": str(run.id),
        "process_candidate_id": str(run.process_candidate_id),
        "status": run.status,
        "candidate_status": candidate_status,
        "call_attempts": run.call_attempts,
        "started_at": started_at.isoformat() if started_at else None,
        "elapsed_seconds": elapsed_seconds,
        "is_stale": is_run_stale(
            run.status,
            run.started_at,
            now,
            settings.stale_calling_timeout_seconds,
            settings.stale_answered_timeout_seconds,
            created_at=run.created_at,
        ),
        "twilio_status_detail": run.twilio_status_detail,
        "twilio_call_sid": run.twilio_call_sid,
    }


def build_process_progress(
    process: HiringProcess,
    candidates: Iterable[ProcessCandidate],
    runs: Iterable[ProfilingRun],
    has_job_description: bool,
    now: datetime | None = None,
) -> ProcessProgress:
    now = now or datetime.now(UTC)
    candidate_list = list(candidates)
    run_list = list(runs)
    candidate_statuses = [str(_value(candidate, "status")) for candidate in candidate_list]
    run_statuses = [str(_value(run, "status")) for run in run_list]
    projections = build_candidate_projections(candidate_list, run_list)
    stage = derive_process_stage(
        str(process.status),
        has_job_description,
        process.question_set_id is not None,
        candidate_statuses,
        run_statuses,
    )
    counts = _candidate_counts(candidate_statuses)
    board_counts = {
        column: sum(item.board_column == column for item in projections) for column in BOARD_COLUMNS
    }
    counts["profiling_queued"] = board_counts[BOARD_COLUMN_QUEUED]
    counts["profiling_active"] = (
        board_counts[BOARD_COLUMN_QUEUED] + board_counts[BOARD_COLUMN_CALLING]
    )
    counts["profiling_completed"] = board_counts[BOARD_COLUMN_COMPLETED]
    counts["profiling_failed"] = board_counts[BOARD_COLUMN_FAILED]
    counts["consistency_attention"] = sum(item.consistency == "ATTENTION" for item in projections)
    counts["calls_active"] = sum(status in {"CALLING", "ANSWERED"} for status in run_statuses)
    counts["profiling_runs"] = len(run_list)
    counts["profiling_runs_terminal"] = sum(
        status in _TERMINAL_RUN_STATUSES for status in run_statuses
    )

    candidate_by_id = {str(candidate.id): str(candidate.status) for candidate in candidate_list}
    active_calls = [
        _active_call_payload(
            run,
            candidate_by_id.get(str(run.process_candidate_id), "UNKNOWN"),
            now,
        )
        for run in run_list
        if run.status in {ProfilingRunStatus.CALLING.value, ProfilingRunStatus.ANSWERED.value}
    ]

    timestamps = [
        timestamp
        for timestamp in [process.updated_at, process.created_at]
        if isinstance(timestamp, datetime)
    ]
    timestamps.extend(
        timestamp
        for item in [*candidate_list, *run_list]
        for timestamp in [getattr(item, "updated_at", None), getattr(item, "created_at", None)]
        if timestamp is not None
    )
    updated_at = max(timestamps) if timestamps else now
    persisted_status = derive_persisted_process_status(str(process.status), stage)
    return ProcessProgress(
        process_id=str(process.id),
        process_status=persisted_status,
        stage=stage,
        stage_label=PROCESS_STAGE_LABELS.get(stage, stage),
        updated_at=updated_at,
        counts=counts,
        active_calls=active_calls,
    )


async def get_process_progress(db: AsyncSession, process_id: Any) -> ProcessProgress:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise LookupError("Proceso no encontrado")
    candidates = (
        (
            await db.execute(
                select(ProcessCandidate).where(ProcessCandidate.process_id == process_id)
            )
        )
        .scalars()
        .all()
    )
    runs = (
        (
            await db.execute(
                select(ProfilingRun)
                .join(ProcessCandidate, ProfilingRun.process_candidate_id == ProcessCandidate.id)
                .where(ProcessCandidate.process_id == process_id)
            )
        )
        .scalars()
        .all()
    )
    has_job_description = bool(
        await db.scalar(
            select(func.count(JobDescription.id)).where(JobDescription.process_id == process_id)
        )
    )
    # build_process_progress es sync y accede a process.updated_at/created_at. Si el
    # autoflush de alguna de las queries de arriba disparó el UPDATE de un cambio
    # pendiente en `process` (p. ej. un campo asignado por el caller antes de llamar
    # aquí), SQLAlchemy expira updated_at (tiene onupdate=func.now(), lo recalcula la
    # DB) y el acceso sync a un atributo expirado revienta con
    # sqlalchemy.exc.MissingGreenlet. Refrescar explícitamente en un contexto async
    # evita que ningún caller futuro reintroduzca este bug.
    if inspect(process).expired:
        await db.refresh(process)
    return build_process_progress(process, candidates, runs, has_job_description)


def get_process_progress_sync(db: Session, process_id: Any) -> ProcessProgress:
    process = db.get(HiringProcess, process_id)
    if not process:
        raise LookupError("Proceso no encontrado")
    candidates = (
        db.execute(select(ProcessCandidate).where(ProcessCandidate.process_id == process_id))
        .scalars()
        .all()
    )
    runs = (
        db.execute(
            select(ProfilingRun)
            .join(ProcessCandidate, ProfilingRun.process_candidate_id == ProcessCandidate.id)
            .where(ProcessCandidate.process_id == process_id)
        )
        .scalars()
        .all()
    )
    has_job_description = bool(
        db.scalar(
            select(func.count(JobDescription.id)).where(JobDescription.process_id == process_id)
        )
    )
    return build_process_progress(process, candidates, runs, has_job_description)


async def sync_process_status(db: AsyncSession, process_id: Any) -> ProcessProgress:
    progress = await get_process_progress(db, process_id)
    process = await db.get(HiringProcess, process_id)
    if process and process.status not in _ADMIN_STATUSES:
        process.status = progress.process_status
    return progress


def sync_process_status_sync(db: Session, process_id: Any) -> ProcessProgress:
    progress = get_process_progress_sync(db, process_id)
    process = db.get(HiringProcess, process_id)
    if process and process.status not in _ADMIN_STATUSES:
        process.status = progress.process_status
    return progress
