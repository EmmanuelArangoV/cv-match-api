import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import RequireRecruiter, RequireRecruiterWithQuery, get_current_user
from src.application.cv.use_cases import AnalyzeCVsUseCase, UploadCVsUseCase
from src.application.hiring_process.progress import sync_process_status
from src.domain.candidate.state_machine import CandidateStateMachine
from src.domain.hiring_process.rules import HiringProcessRules
from src.domain.shared.exceptions import BusinessRuleException, NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    CandidateStatus,
    CostLog,
    HiringProcess,
    ProcessCandidate,
    ProcessStatus,
    User,
    WhatsAppConsentStatus,
)
from src.infrastructure.db.repositories.candidate_repository import CandidateRepository
from src.infrastructure.storage import r2_client


class OverrideBody(BaseModel):
    human_notes: str | None = None
    human_override_match: float | None = None


class AnalysisContextBody(BaseModel):
    analysis_context: str | None = Field(default=None, max_length=4000)


router = APIRouter(prefix="/processes", tags=["Candidates"])


@router.post("/{process_id}/candidates/upload")
async def upload_cvs(
    process_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    use_case = UploadCVsUseCase(db)
    results = await use_case.execute(
        process_id=process_id,
        files=files,
        uploader_id=current_user.id,
    )
    await sync_process_status(db, process_id)
    await db.commit()

    return {
        "uploaded": len(results),
        "message": "CVs cargados; listos para analizar",
        "candidates": [
            {
                "candidate_id": str(r.candidate_id),
                "process_candidate_id": str(r.process_candidate_id),
                "filename": r.filename,
                "task_id": r.task_id,
                "status": r.status,
            }
            for r in results
        ],
    }


@router.post("/{process_id}/candidates/analyze")
async def analyze_cvs(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Encola extracción y normalización de CVs pendientes, sin ejecutar matching."""
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    HiringProcessRules.require_active_process(ProcessStatus(process.status))

    results = await AnalyzeCVsUseCase(db).execute(process_id)
    queued = [result for result in results if result.task_id]
    failed_publications = {
        result.process_candidate_id: result for result in results if result.error is not None
    }
    queued_ids = {result.process_candidate_id for result in queued}

    # Leer los estados posteriores al claim permite informar también los
    # candidatos omitidos (procesándose, ya procesados o matcheados).
    candidates_result = await db.execute(
        select(ProcessCandidate).where(ProcessCandidate.process_id == process_id)
    )
    all_candidates = list(candidates_result.scalars().all())
    skipped = []
    for pc in all_candidates:
        if pc.id in queued_ids:
            continue

        failed = failed_publications.get(pc.id)
        reason = (
            "No se pudo publicar la tarea; el candidato volvió a su estado anterior"
            if failed
            else "El candidato no está pendiente de análisis"
        )
        skipped.append(
            {
                "process_candidate_id": str(pc.id),
                "status": pc.status,
                "reason": reason,
            }
        )

    await sync_process_status(db, process_id)
    await db.commit()

    return {
        "process_id": str(process_id),
        "queued": len(queued),
        "tasks": [
            {
                "process_candidate_id": str(result.process_candidate_id),
                "task_id": result.task_id,
            }
            for result in queued
        ],
        "skipped": skipped,
        "message": ("Análisis de CVs iniciado" if queued else "No hay CVs pendientes de análisis"),
    }


@router.get("/{process_id}/candidates")
async def list_candidates(
    process_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    repo = CandidateRepository(db)
    pcs = await repo.find_process_candidates(process_id)

    # Costo total por candidato en este proceso, en una sola query (evita N+1).
    cost_result = await db.execute(
        select(CostLog.candidate_id, func.sum(CostLog.estimated_cost))
        .where(CostLog.process_id == process_id)
        .group_by(CostLog.candidate_id)
    )
    cost_by_candidate = {cid: float(cost) for cid, cost in cost_result.all()}

    candidates = []
    for rank, pc in enumerate(pcs, start=1):
        explanation = pc.match_explanation or {}
        entry = {
            "rank": rank,
            "process_candidate_id": str(pc.id),
            "candidate_id": str(pc.candidate_id),
            "name": f"{pc.candidate.name} {pc.candidate.last_name}",
            "email": pc.candidate.email,
            "phone": pc.candidate.phone,
            "status": pc.status,
            "match_percentage": float(pc.match_percentage),
            "match_category": pc.match_category,
            "whatsapp_consent": pc.effective_whatsapp_consent_status,
            "normalized_cv_url": (
                pc.cv_version.normalized_file_url_es or pc.cv_version.normalized_file_url
            ),
            "normalized_cv_urls": {
                "es": pc.cv_version.normalized_file_url_es or pc.cv_version.normalized_file_url,
                "en": pc.cv_version.normalized_file_url_en,
            },
            "total_cost": round(cost_by_candidate.get(pc.candidate_id, 0.0), 6),
            "availability_preference": pc.availability_preference,
        }
        # Profile fields from normalized CV
        profile = pc.cv_version.normalized_cv or {}
        location = profile.get("location")
        entry["city"] = location.split(",")[0].strip() if isinstance(location, str) else None
        # Añadir resumen del match si ya fue procesado
        if explanation:
            entry["match_summary"] = explanation.get("summary")
            entry["strengths"] = explanation.get("strengths", [])
            entry["gaps"] = explanation.get("gaps", [])
            entry["breakdown"] = explanation.get("breakdown", {})
        candidates.append(entry)

    return {
        "process_id": str(process_id),
        "total": len(candidates),
        "candidates": candidates,
    }


@router.get("/{process_id}/candidates/{process_candidate_id}")
async def get_candidate_detail(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    explanation = pc.match_explanation or {}
    candidate = pc.candidate
    cv_version = pc.cv_version

    cost_logs_result = await db.execute(
        select(CostLog)
        .where(CostLog.candidate_id == candidate.id, CostLog.process_id == process_id)
        .order_by(CostLog.created_at)
    )
    cost_logs = cost_logs_result.scalars().all()

    return {
        "process_candidate_id": str(pc.id),
        "process_id": str(process_id),
        "candidate": {
            "candidate_id": str(candidate.id),
            "name": f"{candidate.name} {candidate.last_name}",
            "email": candidate.email,
            "phone": candidate.phone,
            "cv_url": cv_version.original_file_url,
            "normalized_cv_url": cv_version.normalized_file_url_es
            or cv_version.normalized_file_url,
            "normalized_cv_urls": {
                "es": cv_version.normalized_file_url_es or cv_version.normalized_file_url,
                "en": cv_version.normalized_file_url_en,
            },
            "profile": cv_version.normalized_cv,
        },
        "status": pc.status,
        "whatsapp_consent": pc.effective_whatsapp_consent_status,
        "availability_preference": pc.availability_preference,
        "analysis_context": pc.analysis_context,
        "human_notes": pc.human_notes,
        "human_override_match": float(pc.human_override_match) if pc.human_override_match else None,
        "match": {
            "percentage": float(pc.match_percentage),
            "category": pc.match_category,
            "summary": explanation.get("summary"),
            "strengths": explanation.get("strengths", []),
            "gaps": explanation.get("gaps", []),
            "breakdown": explanation.get("breakdown", {}),
        }
        if pc.match_percentage is not None
        else None,
        "costs": [
            {
                "operation_type": log.operation_type,
                "provider": log.provider,
                "model_used": log.model_used,
                "tokens_input": log.tokens_input,
                "tokens_cached": log.tokens_cached,
                "tokens_output": log.tokens_output,
                "call_duration_s": log.call_duration_s,
                "estimated_cost": float(log.estimated_cost),
                "currency": log.currency,
                "cost_source": log.cost_source,
                "external_reference": log.external_reference,
                "cost_breakdown": log.cost_breakdown,
                "created_at": log.created_at.isoformat(),
            }
            for log in cost_logs
        ],
        "total_cost": float(sum(log.estimated_cost for log in cost_logs)),
    }


@router.patch("/{process_id}/candidates/{process_candidate_id}/override")
async def patch_candidate_override(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    body: OverrideBody,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    if body.human_notes is not None:
        pc.human_notes = body.human_notes
    if body.human_override_match is not None:
        pc.human_override_match = Decimal(str(body.human_override_match))
    elif body.human_override_match is None and "human_override_match" in body.model_fields_set:
        pc.human_override_match = None

    from src.infrastructure.db.audit import record_audit

    record_audit(db, current_user.id, "MANUAL_OVERRIDE", "ProcessCandidate", pc.id)
    await db.commit()
    return {"status": "updated"}


@router.get("/{process_id}/candidates/{process_candidate_id}/cv/file")
async def get_candidate_cv_file(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    current_user: User = RequireRecruiterWithQuery,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Genera una URL firmada (1 h) para descargar el archivo de CV original."""
    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    r2_key = pc.cv_version.original_file_url
    if not r2_key:
        raise NotFoundException("Este candidato no tiene CV original adjunto.")

    presigned = await r2_client.generate_presigned_url(r2_key, expires_in=3600)
    return RedirectResponse(url=presigned, status_code=302)


@router.post("/{process_id}/candidates/{process_candidate_id}/whatsapp/send")
async def send_candidate_whatsapp(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dispara (o reenvía) manualmente la plantilla de consentimiento de WhatsApp."""
    from src.infrastructure.workers.tasks.whatsapp import send_whatsapp_consent

    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    if not pc.candidate.phone:
        raise BusinessRuleException("Este candidato no tiene teléfono registrado")

    if pc.whatsapp_consent_status in (
        WhatsAppConsentStatus.ACCEPTED.value,
        WhatsAppConsentStatus.REJECTED.value,
    ):
        raise BusinessRuleException(
            f"El candidato ya respondió ({pc.whatsapp_consent_status}), no se puede reenviar"
        )

    task = send_whatsapp_consent.delay(str(pc.id))

    return {
        "process_candidate_id": str(pc.id),
        "task_id": task.id,
        "status": "queued",
    }


@router.get("/{process_id}/candidates/{process_candidate_id}/cv-normalized/file")
async def get_candidate_normalized_cv_file(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    language: Literal["es", "en"] = Query("es"),
    current_user: User = RequireRecruiterWithQuery,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Genera una URL firmada (1 h) para descargar el archivo de CV normalizado."""
    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    r2_key = (
        pc.cv_version.normalized_file_url_es or pc.cv_version.normalized_file_url
        if language == "es"
        else pc.cv_version.normalized_file_url_en
    )
    if not r2_key:
        raise NotFoundException(
            "Este candidato no tiene la variante solicitada del CV normalizado adjunta."
        )

    presigned = await r2_client.generate_presigned_url(r2_key, expires_in=3600)
    return RedirectResponse(url=presigned, status_code=302)


class UpdateCandidateBody(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None


@router.patch("/{process_id}/candidates/{process_candidate_id}")
async def update_candidate(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    body: UpdateCandidateBody,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    candidate = pc.candidate

    if body.name is not None and body.name.strip():
        name_parts = body.name.strip().split(" ", 1)
        candidate.name = name_parts[0]
        candidate.last_name = name_parts[1] if len(name_parts) > 1 else ""

    if body.email is not None and body.email.strip():
        candidate.email = body.email.strip()

    if body.phone is not None:
        candidate.phone = body.phone.strip() if body.phone.strip() else None

    if body.city is not None:
        prof = dict(pc.cv_version.normalized_cv or {})
        prof["location"] = body.city.strip() if body.city.strip() else ""
        pc.cv_version.normalized_cv = prof

    from src.infrastructure.db.audit import record_audit

    record_audit(db, current_user.id, "UPDATE_CANDIDATE", "ProcessCandidate", pc.id)
    await db.commit()
    await db.refresh(candidate)

    return {
        "status": "updated",
        "candidate": {
            "process_candidate_id": str(pc.id),
            "name": f"{candidate.name} {candidate.last_name}".strip(),
            "email": candidate.email,
            "phone": candidate.phone,
            "city": body.city,
        },
    }


@router.patch("/{process_id}/candidates/{process_candidate_id}/analysis-context")
async def update_candidate_analysis_context(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    body: AnalysisContextBody,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Guarda el único comentario libre que se usará durante la extracción del CV."""
    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    editable_statuses = {
        CandidateStatus.LOADED.value,
        CandidateStatus.CV_ERROR.value,
    }
    if pc.status not in editable_statuses:
        raise BusinessRuleException(
            "El contexto solo se puede editar antes de iniciar el análisis del CV."
        )

    normalized_context = body.analysis_context.strip() if body.analysis_context else None
    pc.analysis_context = normalized_context or None

    from src.infrastructure.db.audit import record_audit

    # No duplicamos el texto potencialmente sensible en el log de auditoría.
    record_audit(
        db,
        current_user.id,
        "UPDATE_CV_ANALYSIS_CONTEXT",
        "ProcessCandidate",
        pc.id,
        new_value={"has_analysis_context": bool(normalized_context)},
    )
    await db.commit()
    return {"status": "updated", "analysis_context": pc.analysis_context}


@router.delete("/{process_id}/candidates/{process_candidate_id}")
async def delete_candidate(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    from src.infrastructure.db.audit import record_audit

    record_audit(db, current_user.id, "DELETE_CANDIDATE_FROM_PROCESS", "ProcessCandidate", pc.id)

    await repo.delete_process_candidate(pc)
    await db.commit()

    return {"status": "deleted", "process_candidate_id": str(process_candidate_id)}


@router.patch("/{process_id}/candidates/{process_candidate_id}/discard")
async def discard_candidate(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Descarta un candidato del ranking sin borrar sus datos (RB-008: siempre reversible).

    Solo es una transición válida desde MATCHED o PROFILING_FAILED (ver
    CandidateStateMachine). En cualquier otro estado devuelve 422 — el frontend debe
    ofrecer el borrado físico (DELETE) como alternativa en ese caso.
    """
    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    target = CandidateStateMachine.transition(CandidateStatus(pc.status), CandidateStatus.DISCARDED)
    pc.status = target.value

    from src.infrastructure.db.audit import record_audit

    record_audit(db, current_user.id, "DISCARD_CANDIDATE", "ProcessCandidate", pc.id)
    await db.commit()

    return {"status": "discarded", "process_candidate_id": str(process_candidate_id)}


@router.patch("/{process_id}/candidates/{process_candidate_id}/restore")
async def restore_discarded_candidate(
    process_id: uuid.UUID,
    process_candidate_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revierte un descarte (RB-008: DISCARDED -> MATCHED)."""
    repo = CandidateRepository(db)
    pc = await repo.find_process_candidate_by_id(process_candidate_id)

    if not pc or pc.process_id != process_id:
        raise NotFoundException("Candidato no encontrado en este proceso")

    target = CandidateStateMachine.transition(CandidateStatus(pc.status), CandidateStatus.MATCHED)
    pc.status = target.value

    from src.infrastructure.db.audit import record_audit

    record_audit(db, current_user.id, "RESTORE_DISCARDED_CANDIDATE", "ProcessCandidate", pc.id)
    await db.commit()

    return {"status": "restored", "process_candidate_id": str(process_candidate_id)}
