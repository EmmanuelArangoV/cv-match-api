import asyncio
import csv
import io
import uuid
from typing import Any

import fitz  # pymupdf
from docx import Document as DocxDocument
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import (
    RequireRecruiter,
    RequireRecruiterWithQuery,
    get_current_user,
)
from src.application.hiring_process.jd_parse_usecase import ParseJobDescriptionUseCase
from src.application.hiring_process.progress import (
    build_candidate_projections,
    sync_process_status,
)
from src.domain.hiring_process.rules import HiringProcessRules
from src.domain.shared.exceptions import (
    BusinessRuleException,
    ForbiddenException,
    NotFoundException,
)
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    AIPrompt,
    AITaskType,
    CostLog,
    GlobalBusinessSetting,
    HiringProcess,
    JobDescription,
    OperationType,
    ProcessAIPrompt,
    ProcessCandidate,
    ProcessStatus,
    QuestionSet,
    User,
    UserRole,
    UserStatus,
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
    match_weights_override: dict[str, float] | None = None
    recruiter_id: uuid.UUID | None = None


class CreateJobDescriptionRequest(BaseModel):
    jd_raw_text: str = Field(..., min_length=10)


class UpdateQuestionSetAssignmentRequest(BaseModel):
    question_set_id: uuid.UUID


class UpdateVoiceConfigRequest(BaseModel):
    """Ajustes técnicos de voz para este proceso; el prompt se gestiona por separado."""

    voice_override_agent_id: str | None = None
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


class CreateProcessPromptRequest(BaseModel):
    system_prompt_text: str = Field(..., min_length=1, max_length=50_000)


def _require_process_prompt_editor(process: HiringProcess, current_user: User) -> None:
    if process.status in (ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value):
        raise BusinessRuleException("RB-009: Proceso cerrado o archivado")
    if current_user.role == UserRole.ADMIN.value:
        return
    if current_user.role == UserRole.RECRUITER.value and process.recruiter_id == current_user.id:
        return
    raise ForbiddenException(
        "Solo el recruiter responsable o un administrador puede editar prompts."
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_process(
    body: CreateProcessRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from src.domain.match.value_objects import MatchWeights

    total_budget_setting = await db.scalar(
        select(GlobalBusinessSetting.setting_value).where(
            GlobalBusinessSetting.setting_key == "platform_total_budget"
        )
    )
    configured_limit = (
        total_budget_setting.get("amount", 0) if isinstance(total_budget_setting, dict) else 0
    )
    total_budget = float(configured_limit or 0)
    if total_budget > 0:
        total_spent = float(
            await db.scalar(select(func.coalesce(func.sum(CostLog.estimated_cost), 0)))
        )
        if total_spent >= total_budget:
            raise BusinessRuleException(
                f"El presupuesto total configurado (${total_budget:.2f} USD) ya fue alcanzado. "
                "No se pueden crear más procesos."
            )

    # Validar pesos si se envían
    if body.match_weights_override:
        MatchWeights.from_dict(body.match_weights_override)

    recruiter_id = current_user.id
    if body.recruiter_id:
        if current_user.role not in [UserRole.ADMIN.value, UserRole.TA_LEADER.value]:
            raise BusinessRuleException(
                "No tienes permiso para asignar procesos a otros recruiters."
            )
        assigned_recruiter = await db.scalar(select(User).where(User.id == body.recruiter_id))
        if (
            not assigned_recruiter
            or assigned_recruiter.role != UserRole.RECRUITER.value
            or assigned_recruiter.status != UserStatus.ACTIVE.value
        ):
            raise BusinessRuleException("Selecciona un recruiter activo para asignar el proceso.")
        recruiter_id = assigned_recruiter.id
    elif current_user.role == UserRole.TA_LEADER.value:
        raise BusinessRuleException("Selecciona un recruiter responsable para crear el proceso.")

    process = HiringProcess(
        name=body.name,
        job_title=body.job_title,
        area=body.area,
        seniority=body.seniority,
        budget_max_usd=body.budget_max_usd,
        match_weights_override=body.match_weights_override,
        recruiter_id=recruiter_id,
        status=ProcessStatus.DRAFT.value,
    )
    db.add(process)
    await db.flush()

    # Las plantillas globales se copian al crear el proceso. A partir de aquí cada revisión
    # pertenece exclusivamente al proceso y no cambia cuando Admin publique otra plantilla.
    from src.application.ai.process_prompt_resolver import seed_process_prompts

    await seed_process_prompts(db, process.id, current_user.id)
    await db.commit()
    await db.refresh(process)

    from src.application.notifications.service import create_notification_async

    await create_notification_async(
        db,
        title="Nuevo proceso creado",
        description=(
            f"Se creó el proceso '{process.name}' para el cargo {process.job_title} "
            f"en el área {process.area}."
        ),
        category="PROCESS_CREATED",
        type="INFO",
        user_id=recruiter_id,
        process_id=process.id,
        link=f"/app/procesos/{process.id}",
    )
    await db.commit()

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
) -> dict[str, Any]:
    from src.infrastructure.db.models import UserRole

    query = (
        select(HiringProcess)
        .options(selectinload(HiringProcess.recruiter))
        .order_by(HiringProcess.created_at.desc())
    )

    # RECRUITER solo ve los suyos
    if current_user.role == UserRole.RECRUITER.value:
        query = query.where(HiringProcess.recruiter_id == current_user.id)

    result = await db.execute(query)
    processes = list(result.scalars().all())

    # El estado listado es una proyección del pipeline real. Se sincroniza aquí para
    # reparar procesos que no hayan recibido un evento desde una ejecución antigua.
    if processes:
        sync_results = await asyncio.gather(*[sync_process_status(db, p.id) for p in processes])
        progress_by_process = {p.id: res.as_dict() for p, res in zip(processes, sync_results)}
    else:
        progress_by_process = {}
    await db.commit()

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
                "recruiter_id": str(p.recruiter_id),
                "recruiter_name": f"{p.recruiter.name} {p.recruiter.last_name}",
                "created_at": p.created_at.isoformat(),
                "progress": progress_by_process[p.id],
            }
            for p in processes
        ],
    }


@router.get("/{process_id}")
async def get_process(
    process_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(HiringProcess)
        .where(HiringProcess.id == process_id)
        .options(
            selectinload(HiringProcess.job_descriptions),
            selectinload(HiringProcess.recruiter),
        )
    )
    process: HiringProcess | None = result.scalar_one_or_none()

    if not process:
        raise NotFoundException("Proceso no encontrado")

    await sync_process_status(db, process_id)
    await db.commit()

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
        "recruiter_id": str(process.recruiter_id),
        "recruiter_name": f"{process.recruiter.name} {process.recruiter.last_name}",
        "question_set_id": str(process.question_set_id) if process.question_set_id else None,
        "voice_override_first_message": process.voice_override_first_message,
        "voice_override_language": process.voice_override_language,
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
    """
    Asocia un QuestionSet al proceso (RB-003: requerido para habilitar profiling).
    Siempre clona el set elegido en una copia independiente para este proceso — así el
    set original en /app/sets queda intacto como plantilla, y las personalizaciones de
    un proceso nunca afectan a otro que use la "misma" plantilla.
    """
    from src.api.v1.question_sets import _clone_question_set

    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    HiringProcessRules.require_active_process(ProcessStatus(process.status))

    result = await db.execute(
        select(QuestionSet)
        .where(QuestionSet.id == body.question_set_id)
        .options(selectinload(QuestionSet.questions))
    )
    question_set = result.scalar_one_or_none()
    if not question_set:
        raise NotFoundException("Set de preguntas no encontrado")

    cloned = await _clone_question_set(question_set, db)
    # sync_process_status ANTES de mutar process: internamente accede a
    # process.updated_at/created_at desde una función sync (build_process_progress).
    # Si ya hay un cambio pendiente en `process` (onupdate=func.now() en updated_at),
    # el autoflush de la siguiente query expira ese atributo y el acceso sync explota
    # con sqlalchemy.exc.MissingGreenlet. Mutar después de sincronizar evita el autoflush
    # a mitad de sync_process_status.
    await sync_process_status(db, process_id)
    process.question_set_id = cloned.id
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
            "voice_override_first_message",
            "voice_override_language",
            "voice_override_llm_model",
            "voice_override_voice_id",
            "voice_override_tts_stability",
            "voice_override_tts_speed",
            "voice_override_tts_similarity_boost",
        )
    }


def _serialize_process_prompt(prompt: ProcessAIPrompt) -> dict:
    return {
        "id": str(prompt.id),
        "process_id": str(prompt.process_id),
        "task_type": str(prompt.task_type),
        "version_name": prompt.version_name,
        "system_prompt_text": prompt.system_prompt_text,
        "source_prompt_id": str(prompt.source_prompt_id) if prompt.source_prompt_id else None,
        "is_active": prompt.is_active,
        "created_by": str(prompt.created_by) if prompt.created_by else None,
        "created_at": prompt.created_at.isoformat(),
    }


@router.get("/{process_id}/ai-prompts")
async def list_process_prompts(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")
    if current_user.role == UserRole.RECRUITER.value and process.recruiter_id != current_user.id:
        raise NotFoundException("Proceso no encontrado")

    rows = (
        await db.execute(
            select(ProcessAIPrompt)
            .where(ProcessAIPrompt.process_id == process_id)
            .order_by(ProcessAIPrompt.task_type, ProcessAIPrompt.created_at.desc())
        )
    ).scalars().all()
    return {"prompts": [_serialize_process_prompt(row) for row in rows]}


@router.post("/{process_id}/ai-prompts/{task_type}", status_code=201)
async def create_process_prompt(
    process_id: uuid.UUID,
    task_type: AITaskType,
    body: CreateProcessPromptRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")
    _require_process_prompt_editor(process, current_user)

    from src.application.ai.process_prompt_resolver import next_process_prompt_version
    from src.infrastructure.db.audit import record_audit

    active_rows = (
        await db.execute(
            select(ProcessAIPrompt).where(
                ProcessAIPrompt.process_id == process_id,
                ProcessAIPrompt.task_type == task_type.value,
                ProcessAIPrompt.is_active.is_(True),
            )
        )
    ).scalars().all()
    for active in active_rows:
        active.is_active = False
    # Libera primero el índice parcial de la revisión activa antes de insertar la nueva.
    await db.flush()

    prompt = ProcessAIPrompt(
        process_id=process_id,
        task_type=task_type.value,
        version_name=await next_process_prompt_version(db, process_id, task_type.value),
        system_prompt_text=body.system_prompt_text.strip(),
        source_prompt_id=None,
        is_active=True,
        created_by=current_user.id,
    )
    db.add(prompt)
    await db.flush()
    record_audit(
        db,
        current_user.id,
        "PROCESS_AI_PROMPT_UPDATED",
        "ProcessAIPrompt",
        prompt.id,
        old_value={"active_prompt_ids": [str(row.id) for row in active_rows]},
        new_value={"process_id": str(process_id), "task_type": task_type.value},
    )
    await db.commit()
    await db.refresh(prompt)
    return _serialize_process_prompt(prompt)


@router.post("/{process_id}/ai-prompts/{task_type}/restore-template", status_code=201)
async def restore_process_prompt_template(
    process_id: uuid.UUID,
    task_type: AITaskType,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")
    _require_process_prompt_editor(process, current_user)

    template = await db.scalar(
        select(AIPrompt).where(AIPrompt.task_type == task_type.value, AIPrompt.is_active.is_(True))
    )
    if not template:
        raise BusinessRuleException("No hay una plantilla global activa para esta tarea.")

    from src.application.ai.process_prompt_resolver import next_process_prompt_version
    from src.infrastructure.db.audit import record_audit

    active_rows = (
        await db.execute(
            select(ProcessAIPrompt).where(
                ProcessAIPrompt.process_id == process_id,
                ProcessAIPrompt.task_type == task_type.value,
                ProcessAIPrompt.is_active.is_(True),
            )
        )
    ).scalars().all()
    for active in active_rows:
        active.is_active = False
    # Libera primero el índice parcial de la revisión activa antes de insertar la nueva.
    await db.flush()
    prompt = ProcessAIPrompt(
        process_id=process_id,
        task_type=task_type.value,
        version_name=(
            f"{await next_process_prompt_version(db, process_id, task_type.value)} "
            f"· {template.version_name}"
        ),
        system_prompt_text=template.system_prompt_text,
        source_prompt_id=template.id,
        is_active=True,
        created_by=current_user.id,
    )
    db.add(prompt)
    await db.flush()
    record_audit(
        db,
        current_user.id,
        "PROCESS_AI_PROMPT_RESTORED",
        "ProcessAIPrompt",
        prompt.id,
        old_value={"active_prompt_ids": [str(row.id) for row in active_rows]},
        new_value={
            "process_id": str(process_id),
            "task_type": task_type.value,
            "template_id": str(template.id),
        },
    )
    await db.commit()
    await db.refresh(prompt)
    return _serialize_process_prompt(prompt)


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
    """
    Analiza una JD en texto libre con IA: extrae requisitos (must_have/nice_to_have/
    deal_breakers/summary) y en la misma pasada sugiere una version enriquecida
    (enhanced_jd/recommendations/missing_elements). No persiste nada — el recruiter
    decide si aplica la version mejorada y la guarda via saveJD/createJobDescription.
    """
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    return await ParseJobDescriptionUseCase().execute(
        db,
        body.jd_raw_text,
        process_name=process.name,
        job_title=process.job_title,
        area=process.area,
        seniority=process.seniority,
        process_id=process.id,
        user_id=current_user.id,
    )


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

    # Los estados operativos ya no se cambian manualmente: se derivan del pipeline.
    # CLOSED/ARCHIVED siguen siendo acciones administrativas explícitas.
    if body.status not in {ProcessStatus.CLOSED, ProcessStatus.ARCHIVED}:
        raise BusinessRuleException(
            "Los estados operativos del proceso se calculan automáticamente; "
            "solo CLOSED y ARCHIVED pueden cambiarse manualmente."
        )

    new_status = HiringProcessStateMachine.transition(ProcessStatus(process.status), body.status)
    process.status = new_status.value
    await db.commit()
    await db.refresh(process)

    return {
        "process_id": str(process.id),
        "status": process.status,
    }


@router.get("/{process_id}/progress")
async def get_process_progress_endpoint(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Devuelve la única proyección de etapa, contadores y llamadas activas."""
    try:
        progress = await sync_process_status(db, process_id)
    except LookupError as exc:
        raise NotFoundException(str(exc)) from exc
    await db.commit()
    return progress.as_dict()


@router.get("/{process_id}/pipeline")
async def get_process_pipeline(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Una tarjeta por candidato, proyectada por la misma fuente del progreso."""

    result = await db.execute(
        select(HiringProcess)
        .where(HiringProcess.id == process_id)
        .options(
            selectinload(HiringProcess.recruiter),
            selectinload(HiringProcess.process_candidates).selectinload(ProcessCandidate.candidate),
            selectinload(HiringProcess.process_candidates).selectinload(
                ProcessCandidate.profiling_runs
            ),
        )
    )
    process = result.scalar_one_or_none()
    if not process:
        raise NotFoundException("Proceso no encontrado")
    if current_user.role == UserRole.RECRUITER.value and process.recruiter_id != current_user.id:
        raise NotFoundException("Proceso no encontrado")

    candidates = list(process.process_candidates)
    runs = [run for pc in candidates for run in pc.profiling_runs]
    cards = build_candidate_projections(candidates, runs)
    return {
        "process_id": str(process.id),
        "total": len(cards),
        "candidates": [card.as_dict() for card in cards],
    }


@router.get("/{process_id}/metrics", response_model=dict)
async def get_process_metrics(
    process_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import func

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

    # Costo desglosado por operacion, agrupado en las 4 categorias que le importan al
    # recruiter: voz (ElevenLabs), twilio (telefonia), whatsapp, y llm (todo lo demas
    # basado en OpenAI: extraccion de CV, match, mejora de JD, evaluacion de profiling).
    by_op_query = (
        select(CostLog.operation_type, func.sum(CostLog.estimated_cost))
        .where(CostLog.process_id == process_id)
        .group_by(CostLog.operation_type)
    )
    by_op_result = await db.execute(by_op_query)
    cost_by_operation = {op: float(cost) for op, cost in by_op_result.all()}

    category_map: dict[str, list[str]] = {
        "storage": [OperationType.CV_STORAGE.value],
        "voz": [OperationType.VOICE_CALL.value],
        "twilio": [OperationType.TWILIO_CALL.value],
        "whatsapp": [OperationType.WHATSAPP_MESSAGE.value],
        "llm": [
            OperationType.CV_EXTRACTION.value,
            OperationType.CV_EMBEDDING.value,
            OperationType.CV_MATCH.value,
            OperationType.JD_ENHANCEMENT.value,
            OperationType.ANSWER_EVALUATION.value,
            OperationType.VOICE_TRANSCRIPTION.value,
            OperationType.WHATSAPP_AI.value,
        ],
    }
    cost_by_category = {
        category: round(sum(cost_by_operation.get(op, 0.0) for op in ops), 6)
        for category, ops in category_map.items()
    }

    return {
        "process_id": str(process.id),
        "total_cvs": sum(status_counts.values()),
        "status_distribution": status_counts,
        "match_distribution": match_counts,
        "total_cost_usd": float(total_cost),
        "budget_max_usd": float(process.budget_max_usd),
        "cost_by_category": cost_by_category,
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
    process_id: uuid.UUID, current_user: User = RequireRecruiter, db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    query = (
        select(ProcessCandidate)
        .where(ProcessCandidate.process_id == process_id)
        .options(selectinload(ProcessCandidate.candidate))
        .order_by(ProcessCandidate.match_percentage.desc().nullslast())
    )
    result = await db.execute(query)
    candidates = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Email", "Status", "Match Percentage", "Match Category", "Created At"])
    for c in candidates:
        email = c.candidate.email if c.candidate else ""
        writer.writerow(
            [str(c.id), email, c.status, c.match_percentage, c.match_category, c.created_at]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=ranking_{process_id}.csv"},
    )


@router.get("/{process_id}/export/costs")
async def export_costs(
    process_id: uuid.UUID, current_user: User = RequireRecruiter, db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")

    query = (
        select(CostLog).where(CostLog.process_id == process_id).order_by(CostLog.created_at.desc())
    )
    result = await db.execute(query)
    logs = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Operation Type", "Model Used", "Estimated Cost", "Created At"])
    for log in logs:
        writer.writerow(
            [str(log.id), log.operation_type, log.model_used, log.estimated_cost, log.created_at]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=costs_{process_id}.csv"},
    )
