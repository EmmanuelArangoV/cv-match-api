import io
import uuid

import fitz  # pymupdf
from docx import Document as DocxDocument
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import (
    RequireRecruiter,
    RequireRecruiterWithQuery,
    get_current_user,
)
from src.application.hiring_process.enhance_jd_usecase import EnhanceJDUseCase
from src.application.hiring_process.jd_parse_usecase import ParseJobDescriptionUseCase
from src.domain.hiring_process.rules import HiringProcessRules
from src.domain.shared.exceptions import BusinessRuleException, NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    HiringProcess,
    JobDescription,
    ProcessStatus,
    QuestionSet,
    User,
)
from src.infrastructure.storage import r2_client

# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------


def _extract_text_from_pdf(data: bytes) -> str:
    doc = fitz.open(stream=data, filetype="pdf")
    parts = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(parts).strip()


def _extract_text_from_docx(data: bytes) -> str:
    doc = DocxDocument(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()


def _extract_text(data: bytes, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return _extract_text_from_pdf(data)
    if ext in ("docx", "doc"):
        return _extract_text_from_docx(data)
    if ext == "txt":
        return data.decode("utf-8", errors="replace").strip()
    raise BusinessRuleException(f"Formato '{ext}' no soportado. Usa PDF, DOCX o TXT.")


router = APIRouter(prefix="/processes", tags=["Processes"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateProcessRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    job_title: str = Field(..., min_length=1, max_length=255)
    area: str = Field(..., min_length=1, max_length=100)
    seniority: str = Field(..., min_length=1, max_length=50)
    budget_max_usd: float = Field(default=0.0, ge=0)
    match_weights_override: dict | None = None


class CreateJobDescriptionRequest(BaseModel):
    jd_raw_text: str = Field(..., min_length=10)


class UpdateQuestionSetAssignmentRequest(BaseModel):
    question_set_id: uuid.UUID


class UpdateVoiceConfigRequest(BaseModel):
    """Override de configuracion de voz (ElevenLabs) para este proceso. Tiene prioridad
    sobre los default_* del QuestionSet asociado cuando un campo no es None."""

    voice_override_agent_id: str | None = None
    voice_override_system_prompt: str | None = None
    voice_override_first_message: str | None = None
    voice_override_language: str | None = None
    voice_override_llm_model: str | None = None
    voice_override_voice_id: str | None = None
    voice_override_tts_stability: float | None = None
    voice_override_tts_speed: float | None = None
    voice_override_tts_similarity_boost: float | None = None


class UpdateProcessRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    job_title: str | None = Field(None, min_length=1, max_length=255)
    area: str | None = Field(None, min_length=1, max_length=100)
    seniority: str | None = Field(None, min_length=1, max_length=50)
    budget_max_usd: float | None = Field(None, ge=0)


class UpdateProcessStatusRequest(BaseModel):
    status: ProcessStatus


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_process(
    body: CreateProcessRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from src.domain.match.value_objects import MatchWeights

    # Validar pesos si se envían
    if body.match_weights_override:
        MatchWeights.from_dict(body.match_weights_override)

    process = HiringProcess(
        name=body.name,
        job_title=body.job_title,
        area=body.area,
        seniority=body.seniority,
        budget_max_usd=body.budget_max_usd,
        match_weights_override=body.match_weights_override,
        recruiter_id=current_user.id,
        status=ProcessStatus.DRAFT.value,
    )
    db.add(process)
    await db.commit()
    await db.refresh(process)

    return {
        "process_id": str(process.id),
        "name": process.name,
        "job_title": process.job_title,
        "area": process.area,
        "seniority": process.seniority,
        "status": process.status,
        "budget_max_usd": float(process.budget_max_usd),
    }


@router.get("")
async def list_processes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from src.infrastructure.db.models import UserRole

    query = select(HiringProcess).order_by(HiringProcess.created_at.desc())

    # RECRUITER solo ve los suyos
    if current_user.role == UserRole.RECRUITER.value:
        query = query.where(HiringProcess.recruiter_id == current_user.id)

    result = await db.execute(query)
    processes = list(result.scalars().all())

    return {
        "total": len(processes),
        "processes": [
            {
                "process_id": str(p.id),
                "name": p.name,
                "job_title": p.job_title,
                "area": p.area,
                "seniority": p.seniority,
                "status": p.status,
                "budget_max_usd": float(p.budget_max_usd),
                "created_at": p.created_at.isoformat(),
            }
            for p in processes
        ],
    }


@router.get("/{process_id}")
async def get_process(
    process_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(HiringProcess)
        .where(HiringProcess.id == process_id)
        .options(selectinload(HiringProcess.job_descriptions))
    )
    process: HiringProcess | None = result.scalar_one_or_none()

    if not process:
        raise NotFoundException("Proceso no encontrado")

    jds = sorted(process.job_descriptions, key=lambda j: j.version, reverse=True)
    active_jd = jds[0] if jds else None

    return {
        "process_id": str(process.id),
        "name": process.name,
        "job_title": process.job_title,
        "area": process.area,
        "seniority": process.seniority,
        "status": process.status,
        "budget_max_usd": float(process.budget_max_usd),
        "match_weights": process.match_weights_override,
        "question_set_id": str(process.question_set_id) if process.question_set_id else None,
        "voice_override_system_prompt": process.voice_override_system_prompt,
        "voice_override_first_message": process.voice_override_first_message,
        "job_description": {
            "jd_id": str(active_jd.id),
            "version": active_jd.version,
            "text_preview": active_jd.jd_raw_text[:300] + "..."
            if len(active_jd.jd_raw_text) > 300
            else active_jd.jd_raw_text,
            "jd_raw_text": active_jd.jd_raw_text,
            "jd_file_url": (active_jd.structured_jd or {}).get("jd_file_url"),
            "original_filename": (active_jd.structured_jd or {}).get("original_filename"),
            "created_at": active_jd.created_at.isoformat(),
        }
        if active_jd
        else None,
        "created_at": process.created_at.isoformat(),
        "updated_at": process.updated_at.isoformat(),
    }


@router.patch("/{process_id}/question-set")
async def update_process_question_set(
    process_id: uuid.UUID,
    body: UpdateQuestionSetAssignmentRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Asocia un QuestionSet al proceso (RB-003: requerido para habilitar profiling)."""
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    HiringProcessRules.require_active_process(ProcessStatus(process.status))

    question_set = await db.get(QuestionSet, body.question_set_id)
    if not question_set:
        raise NotFoundException("Set de preguntas no encontrado")

    process.question_set_id = question_set.id
    await db.commit()

    return {
        "process_id": str(process.id),
        "question_set_id": str(process.question_set_id),
    }


@router.patch("/{process_id}/voice-config")
async def update_process_voice_config(
    process_id: uuid.UUID,
    body: UpdateVoiceConfigRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    for field in (
        "voice_override_agent_id",
        "voice_override_system_prompt",
        "voice_override_first_message",
        "voice_override_language",
        "voice_override_llm_model",
        "voice_override_voice_id",
        "voice_override_tts_stability",
        "voice_override_tts_speed",
        "voice_override_tts_similarity_boost",
    ):
        value = getattr(body, field)
        if value is not None:
            setattr(process, field, value)

    await db.commit()
    await db.refresh(process)

    return {
        field: getattr(process, field)
        for field in (
            "voice_override_agent_id",
            "voice_override_system_prompt",
            "voice_override_first_message",
            "voice_override_language",
            "voice_override_llm_model",
            "voice_override_voice_id",
            "voice_override_tts_stability",
            "voice_override_tts_speed",
            "voice_override_tts_similarity_boost",
        )
    }


@router.post("/{process_id}/job-description", status_code=201)
async def create_job_description(
    process_id: uuid.UUID,
    body: CreateJobDescriptionRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(HiringProcess)
        .where(HiringProcess.id == process_id)
        .options(selectinload(HiringProcess.job_descriptions))
    )
    process: HiringProcess | None = result.scalar_one_or_none()

    if not process:
        raise NotFoundException("Proceso no encontrado")

    if process.status in (ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value):
        raise BusinessRuleException("RB-009: Proceso cerrado o archivado")

    # Versión incremental
    next_version = max((jd.version for jd in process.job_descriptions), default=0) + 1

    jd = JobDescription(
        process_id=process_id,
        version=next_version,
        jd_raw_text=body.jd_raw_text,
        structured_jd={"version": next_version, "raw": body.jd_raw_text},
    )
    db.add(jd)
    await db.commit()
    await db.refresh(jd)

    return {
        "jd_id": str(jd.id),
        "process_id": str(process_id),
        "version": jd.version,
        "created_at": jd.created_at.isoformat(),
    }


@router.post("/{process_id}/job-description/parse")
async def parse_job_description(
    process_id: uuid.UUID,
    body: CreateJobDescriptionRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Analiza una JD en texto libre con IA. No persiste nada (ver saveJD)."""
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    return await ParseJobDescriptionUseCase().execute(body.jd_raw_text)


@router.post("/{process_id}/job-description/enhance", status_code=201)
async def enhance_job_description(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mejora la JD actual con IA y la guarda como una nueva versión."""
    result = await db.execute(
        select(HiringProcess)
        .where(HiringProcess.id == process_id)
        .options(selectinload(HiringProcess.job_descriptions))
    )
    process: HiringProcess | None = result.scalar_one_or_none()

    if not process:
        raise NotFoundException("Proceso no encontrado")

    if process.status in (ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value):
        raise BusinessRuleException("RB-009: Proceso cerrado o archivado")

    active_jd = max(process.job_descriptions, key=lambda j: j.version, default=None)
    if not active_jd:
        raise BusinessRuleException("No hay una JD para mejorar. Sube o crea una JD primero.")

    enhancement_result = await EnhanceJDUseCase().execute(active_jd.jd_raw_text)
    enhanced_text = enhancement_result["enhanced_jd"]

    next_version = active_jd.version + 1

    new_jd = JobDescription(
        process_id=process_id,
        version=next_version,
        jd_raw_text=enhanced_text,
        structured_jd={
            "version": next_version,
            "raw": enhanced_text,
            "ai_enhanced": True,
            "recommendations": enhancement_result["recommendations"],
            "missing_elements": enhancement_result["missing_elements"],
        },
    )
    db.add(new_jd)
    await db.commit()
    await db.refresh(new_jd)

    return {
        "jd_id": str(new_jd.id),
        "process_id": str(process_id),
        "version": new_jd.version,
        "recommendations": enhancement_result["recommendations"],
        "missing_elements": enhancement_result["missing_elements"],
        "created_at": new_jd.created_at.isoformat(),
    }


@router.post("/{process_id}/job-description/upload", status_code=201)
async def upload_job_description_file(
    process_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sube un archivo PDF/DOCX/TXT como JD, extrae el texto y lo guarda en R2."""
    MAX_SIZE = 10 * 1024 * 1024  # 10 MB
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise BusinessRuleException("El archivo supera el límite de 10 MB")

    filename = file.filename or "job_description.pdf"
    raw_text = _extract_text(content, filename)
    if not raw_text:
        raise BusinessRuleException(
            "No se pudo extraer texto del archivo. Verifica que el PDF no sea una imagen escaneada."
        )

    result = await db.execute(
        select(HiringProcess)
        .where(HiringProcess.id == process_id)
        .options(selectinload(HiringProcess.job_descriptions))
    )
    process: HiringProcess | None = result.scalar_one_or_none()
    if not process:
        raise NotFoundException("Proceso no encontrado")
    if process.status in (ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value):
        raise BusinessRuleException("RB-009: Proceso cerrado o archivado")

    next_version = max((jd.version for jd in process.job_descriptions), default=0) + 1

    # Guardamos en R2 antes de crear el registro para tener el id
    jd_id = uuid.uuid4()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
    r2_key = f"jds/{process_id}/{jd_id}.{ext}"
    content_type_map = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
    }
    await r2_client.upload_file(
        r2_key, content, content_type_map.get(ext, "application/octet-stream")
    )

    jd = JobDescription(
        id=jd_id,
        process_id=process_id,
        version=next_version,
        jd_raw_text=raw_text,
        structured_jd={
            "version": next_version,
            "raw": raw_text,
            "jd_file_url": r2_key,
            "original_filename": filename,
        },
    )
    db.add(jd)
    await db.commit()
    await db.refresh(jd)

    return {
        "jd_id": str(jd.id),
        "process_id": str(process_id),
        "version": jd.version,
        "jd_file_url": r2_key,
        "original_filename": filename,
        "text_length": len(raw_text),
        "created_at": jd.created_at.isoformat(),
    }


@router.get("/{process_id}/job-description/file")
async def get_job_description_file(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiterWithQuery,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Genera una URL firmada (1 h) para descargar el archivo de la JD activa."""
    result = await db.execute(
        select(HiringProcess)
        .where(HiringProcess.id == process_id)
        .options(selectinload(HiringProcess.job_descriptions))
    )
    process: HiringProcess | None = result.scalar_one_or_none()
    if not process:
        raise NotFoundException("Proceso no encontrado")

    active_jd = max(process.job_descriptions, key=lambda j: j.version, default=None)
    if not active_jd:
        raise NotFoundException("No hay Job Description guardada para este proceso")

    r2_key = (active_jd.structured_jd or {}).get("jd_file_url")
    if not r2_key:
        raise NotFoundException("Esta JD no tiene archivo adjunto, solo texto.")

    presigned = await r2_client.generate_presigned_url(r2_key, expires_in=3600)
    return RedirectResponse(url=presigned, status_code=302)


@router.patch("/{process_id}", response_model=dict)
async def update_process(
    process_id: uuid.UUID,
    body: UpdateProcessRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    HiringProcessRules.require_active_process(ProcessStatus(process.status))

    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    for field, value in update_data.items():
        setattr(process, field, value)

    await db.commit()
    await db.refresh(process)

    return {
        "process_id": str(process.id),
        "name": process.name,
        "job_title": process.job_title,
        "area": process.area,
        "seniority": process.seniority,
        "status": process.status,
        "budget_max_usd": float(process.budget_max_usd),
    }


@router.patch("/{process_id}/status", response_model=dict)
async def update_process_status(
    process_id: uuid.UUID,
    body: UpdateProcessStatusRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from src.domain.hiring_process.state_machine import HiringProcessStateMachine

    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    new_status = HiringProcessStateMachine.transition(ProcessStatus(process.status), body.status)
    process.status = new_status.value
    await db.commit()
    await db.refresh(process)

    return {
        "process_id": str(process.id),
        "status": process.status,
    }


@router.get("/{process_id}/metrics", response_model=dict)
async def get_process_metrics(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import func

    from src.infrastructure.db.models import CostLog, ProcessCandidate

    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    # Counts by status
    status_query = (
        select(ProcessCandidate.status, func.count())
        .where(ProcessCandidate.process_id == process_id)
        .group_by(ProcessCandidate.status)
    )
    status_result = await db.execute(status_query)
    status_counts = {k: v for k, v in status_result.all()}

    # Counts by match category
    match_query = (
        select(ProcessCandidate.match_category, func.count())
        .where(
            ProcessCandidate.process_id == process_id, ProcessCandidate.match_category.isnot(None)
        )
        .group_by(ProcessCandidate.match_category)
    )
    match_result = await db.execute(match_query)
    match_counts = {k: v for k, v in match_result.all()}

    # Total cost
    cost_query = select(func.sum(CostLog.estimated_cost)).where(CostLog.process_id == process_id)
    cost_result = await db.execute(cost_query)
    total_cost = cost_result.scalar() or 0.0

    return {
        "process_id": str(process.id),
        "total_cvs": sum(status_counts.values()),
        "status_distribution": status_counts,
        "match_distribution": match_counts,
        "total_cost_usd": float(total_cost),
        "budget_max_usd": float(process.budget_max_usd),
    }


@router.get("/{process_id}/job-descriptions", response_model=list[dict])
async def list_job_descriptions(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    result = await db.execute(
        select(JobDescription)
        .where(JobDescription.process_id == process_id)
        .order_by(JobDescription.version.desc())
    )
    jds = list(result.scalars().all())

    return [
        {
            "jd_id": str(jd.id),
            "version": jd.version,
            "text_preview": jd.jd_raw_text[:300] + "..."
            if len(jd.jd_raw_text) > 300
            else jd.jd_raw_text,
            "jd_file_url": (jd.structured_jd or {}).get("jd_file_url"),
            "original_filename": (jd.structured_jd or {}).get("original_filename"),
            "created_at": jd.created_at.isoformat(),
        }
        for jd in jds
    ]


@router.get("/{process_id}/export/ranking")
async def export_ranking(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    query = select(ProcessCandidate).where(ProcessCandidate.process_id == process_id).order_by(ProcessCandidate.match_score.desc().nullslast())
    result = await db.execute(query)
    candidates = result.scalars().all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Email", "Status", "Match Score", "Match Category", "Profiling Score", "Created At"])
    for c in candidates:
        email = c.candidate.email if c.candidate else ""
        writer.writerow([str(c.id), email, c.status, c.match_score, c.match_category, c.profiling_score, c.created_at])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=ranking_{process_id}.csv"}
    )

@router.get("/{process_id}/export/costs")
async def export_costs(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    query = select(CostLog).where(CostLog.process_id == process_id).order_by(CostLog.created_at.desc())
    result = await db.execute(query)
    logs = result.scalars().all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Action", "Provider", "Estimated Cost", "Created At"])
    for log in logs:
        writer.writerow([str(log.id), log.action, log.provider, log.estimated_cost, log.created_at])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=costs_{process_id}.csv"}
    )
