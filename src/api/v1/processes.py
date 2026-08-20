import csv
import io
import uuid
from typing import Any

import fitz  # pymupdf
from docx import Document as DocxDocument
from fastapi import APIRouter, Depends, File, Query, UploadFile
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
    PROCESS_STAGE_LABELS,
    build_candidate_projections,
    get_process_progress_batch,
    process_stage_sql_expression,
    sync_process_status,
)
from src.domain.candidate.state_machine import CandidateStateMachine
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
    CandidateStatus,
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
    WhatsAppTemplate,
    WhatsAppTemplateStatus,
)
from src.infrastructure.messaging.whatsapp_client import template_bindings_are_valid
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
    """Ajustes técnicos de voz; saludo e instrucciones se versionan por separado."""

    voice_override_agent_id: str | None = None
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


class UpdateWhatsAppTemplateAssignmentRequest(BaseModel):
    template_id: uuid.UUID


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


def _require_process_prompt_task(task_type: AITaskType) -> None:
    from src.application.ai.process_prompt_resolver import PROCESS_PROMPT_TASKS

    if task_type.value not in PROCESS_PROMPT_TASKS:
        raise BusinessRuleException(
            "Este prompt es global y solo puede administrarse desde los ajustes de Admin."
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

    default_whatsapp_template = await db.scalar(
        select(WhatsAppTemplate).where(
            WhatsAppTemplate.is_default.is_(True),
            WhatsAppTemplate.is_enabled.is_(True),
            WhatsAppTemplate.status == WhatsAppTemplateStatus.APPROVED.value,
        )
    )
    process = HiringProcess(
        name=body.name,
        job_title=body.job_title,
        area=body.area,
        seniority=body.seniority,
        budget_max_usd=body.budget_max_usd,
        match_weights_override=body.match_weights_override,
        recruiter_id=recruiter_id,
        whatsapp_template_id=(
            default_whatsapp_template.id if default_whatsapp_template else None
        ),
        status=ProcessStatus.DRAFT.value,
    )
    db.add(process)
    await db.flush()

    # Solo WhatsApp y agente de llamada pertenecen al proceso. Extraccion, match, mejora de JD
    # y evaluacion de profiling siempre resuelven la version global activa en runtime.
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

    # Esta ruta se conserva por compatibilidad, pero ya no reconcilia ni escribe. La proyeccion
    # se carga en bloque; los consumidores nuevos deben preferir /home u /options.
    progress_by_process = {
        process_id: progress.as_dict()
        for process_id, progress in (await get_process_progress_batch(db, processes)).items()
    }

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


@router.get("/home")
async def list_home_processes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    stage: str | None = Query(default=None),
    recruiter_id: uuid.UUID | None = Query(default=None),
    area: str | None = Query(default=None, min_length=1, max_length=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Listado paginado del inicio, sin reconciliaciones ni escrituras en la base de datos."""

    allowed_stages = set(PROCESS_STAGE_LABELS)
    if stage and stage not in allowed_stages:
        raise BusinessRuleException("La etapa seleccionada no es válida.")

    role_filters: list[Any] = []
    if current_user.role == UserRole.RECRUITER.value:
        role_filters.append(HiringProcess.recruiter_id == current_user.id)

    filters = list(role_filters)
    if recruiter_id and current_user.role != UserRole.RECRUITER.value:
        filters.append(HiringProcess.recruiter_id == recruiter_id)
    if area:
        filters.append(HiringProcess.area == area)

    stage_expression = process_stage_sql_expression()
    if stage in (ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value):
        # Estos estados terminales son persistidos y no necesitan evaluar la proyeccion CASE.
        filters.append(HiringProcess.status == stage)
    elif stage:
        filters.append(stage_expression == stage)
    else:
        # Cerrados y archivados siguen disponibles desde el filtro de etapa, pero no ralentizan
        # ni distraen la vista operativa inicial.
        filters.append(
            HiringProcess.status.notin_((ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value))
        )

    summary_row = (
        await db.execute(
            select(
                func.count(HiringProcess.id.distinct()),
                func.count(HiringProcess.id.distinct()).filter(
                    HiringProcess.status.notin_(
                        (ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value)
                    )
                ),
                func.count(ProcessCandidate.id).filter(
                    ProcessCandidate.status.notin_(("LOADED", "CV_PROCESSING", "CV_ERROR"))
                ),
                func.count(ProcessCandidate.id).filter(
                    ProcessCandidate.status == "PROFILING_COMPLETED"
                ),
            )
            .select_from(HiringProcess)
            .outerjoin(ProcessCandidate, ProcessCandidate.process_id == HiringProcess.id)
            .where(*filters)
        )
    ).one()
    total = int(summary_row[0] or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    effective_page = min(page, total_pages)
    page_rows = (
        await db.execute(
            select(
                HiringProcess,
                User.name,
                User.last_name,
                select(JobDescription.id)
                .where(JobDescription.process_id == HiringProcess.id)
                .exists()
                .label("has_job_description"),
            )
            .join(User, User.id == HiringProcess.recruiter_id)
            .where(*filters)
            .order_by(HiringProcess.created_at.desc())
            .offset((effective_page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    processes = [row[0] for row in page_rows]
    recruiter_names = {row[0].id: f"{row[1]} {row[2]}".strip() for row in page_rows}
    has_job_description = {row[0].id: bool(row[3]) for row in page_rows}
    progress_by_process = {
        process_id: progress.as_dict()
        for process_id, progress in (
            await get_process_progress_batch(db, processes, has_job_description)
        ).items()
    }

    option_rows = (
        await db.execute(
            select(
                HiringProcess.area,
                User.id,
                User.name,
                User.last_name,
            )
            .join(User, User.id == HiringProcess.recruiter_id)
            .where(*role_filters)
            .distinct()
        )
    ).all()
    areas = sorted({row.area for row in option_rows})
    recruiters = sorted(
        {(str(row.id), f"{row.name} {row.last_name}".strip()) for row in option_rows},
        key=lambda item: item[1].casefold(),
    )

    return {
        "items": [
            {
                "process_id": str(process.id),
                "name": process.name,
                "job_title": process.job_title,
                "area": process.area,
                "seniority": process.seniority,
                "status": process.status,
                "budget_max_usd": float(process.budget_max_usd),
                "recruiter_id": str(process.recruiter_id),
                "recruiter_name": recruiter_names[process.id],
                "created_at": process.created_at.isoformat(),
                "progress": progress_by_process[process.id],
            }
            for process in processes
        ],
        "pagination": {
            "page": effective_page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
        "summary": {
            "active_processes": int(summary_row[1] or 0),
            "cv_processed": int(summary_row[2] or 0),
            "profiling_completed": int(summary_row[3] or 0),
        },
        "filter_options": {
            "areas": areas,
            "recruiters": [
                {"id": recruiter_option_id, "name": name}
                for recruiter_option_id, name in recruiters
            ],
        },
    }


@router.get("/options")
async def list_process_options(
    include_inactive: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Opciones livianas para selectores; no carga candidatos, corridas ni progreso."""

    filters: list[Any] = []
    if current_user.role == UserRole.RECRUITER.value:
        filters.append(HiringProcess.recruiter_id == current_user.id)
    if not include_inactive:
        filters.append(
            HiringProcess.status.notin_((ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value))
        )
    rows = (
        await db.execute(
            select(HiringProcess.id, HiringProcess.name, HiringProcess.status)
            .where(*filters)
            .order_by(HiringProcess.name)
        )
    ).all()
    return {
        "processes": [
            {"process_id": str(process_id), "name": name, "status": status}
            for process_id, name, status in rows
        ]
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
            selectinload(HiringProcess.whatsapp_template),
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
        "voice_override_language": process.voice_override_language,
        "whatsapp_template": (
            {
                "id": str(process.whatsapp_template.id),
                "name": process.whatsapp_template.name,
                "language": process.whatsapp_template.language,
                "status": str(process.whatsapp_template.status),
                "is_enabled": process.whatsapp_template.is_enabled,
                "components": process.whatsapp_template.components or [],
                "variable_bindings": process.whatsapp_template.variable_bindings or {},
            }
            if process.whatsapp_template
            else None
        ),
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
    _require_process_prompt_editor(process, current_user)

    for field in (
        "voice_override_agent_id",
        "voice_override_language",
        "voice_override_llm_model",
        "voice_override_voice_id",
        "voice_override_tts_stability",
        "voice_override_tts_speed",
        "voice_override_tts_similarity_boost",
    ):
        if field in body.model_fields_set:
            setattr(process, field, getattr(body, field))

    await db.commit()
    await db.refresh(process)

    return {
        field: getattr(process, field)
        for field in (
            "voice_override_agent_id",
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
        "first_message_text": prompt.first_message_text,
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
        (
            await db.execute(
                select(ProcessAIPrompt)
                .where(
                    ProcessAIPrompt.process_id == process_id,
                    ProcessAIPrompt.task_type.in_(("WHATSAPP_MESSAGE", "VOICE_CALL_AGENT")),
                )
                .order_by(ProcessAIPrompt.task_type, ProcessAIPrompt.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"prompts": [_serialize_process_prompt(row) for row in rows]}


@router.patch("/{process_id}/whatsapp-template")
async def assign_process_whatsapp_template(
    process_id: uuid.UUID,
    body: UpdateWhatsAppTemplateAssignmentRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    process = await db.get(HiringProcess, process_id)
    if not process:
        raise NotFoundException("Proceso no encontrado")
    _require_process_prompt_editor(process, current_user)
    template = await db.get(WhatsAppTemplate, body.template_id)
    if not template:
        raise NotFoundException("Plantilla de WhatsApp no encontrada")
    if (
        str(template.status) != WhatsAppTemplateStatus.APPROVED.value
        or not template.is_enabled
        or not template_bindings_are_valid(
            template.components or [], template.variable_bindings or {}
        )
    ):
        raise BusinessRuleException(
            "La plantilla debe estar aprobada, habilitada y tener sus variables completas."
        )
    from src.api.v1.whatsapp_templates import serialize_template
    from src.infrastructure.db.audit import record_audit

    previous_id = process.whatsapp_template_id
    process.whatsapp_template_id = template.id
    record_audit(
        db,
        current_user.id,
        "PROCESS_WHATSAPP_TEMPLATE_ASSIGNED",
        "HiringProcess",
        process.id,
        old_value={"whatsapp_template_id": str(previous_id) if previous_id else None},
        new_value={"whatsapp_template_id": str(template.id)},
    )
    await db.commit()
    return {"template": serialize_template(template)}


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
    _require_process_prompt_task(task_type)

    from src.application.ai.process_prompt_resolver import next_process_prompt_version
    from src.infrastructure.db.audit import record_audit

    active_rows = (
        (
            await db.execute(
                select(ProcessAIPrompt).where(
                    ProcessAIPrompt.process_id == process_id,
                    ProcessAIPrompt.task_type == task_type.value,
                    ProcessAIPrompt.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    preserved_greeting = next(
        ((row.first_message_text or "").strip() for row in active_rows if row.first_message_text),
        "",
    )
    if task_type == AITaskType.VOICE_CALL_AGENT and not preserved_greeting:
        raise BusinessRuleException(
            "El proceso no tiene un saludo activo. Aplica primero una plantilla de Admin."
        )
    for active in active_rows:
        active.is_active = False
    # Libera primero el índice parcial de la revisión activa antes de insertar la nueva.
    await db.flush()

    prompt = ProcessAIPrompt(
        process_id=process_id,
        task_type=task_type.value,
        version_name=await next_process_prompt_version(db, process_id, task_type.value),
        system_prompt_text=body.system_prompt_text.strip(),
        first_message_text=(
            preserved_greeting if task_type == AITaskType.VOICE_CALL_AGENT else None
        ),
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
    _require_process_prompt_task(task_type)

    template = await db.scalar(
        select(AIPrompt).where(AIPrompt.task_type == task_type.value, AIPrompt.is_active.is_(True))
    )
    if not template:
        raise BusinessRuleException("No hay una plantilla global activa para esta tarea.")
    if task_type == AITaskType.VOICE_CALL_AGENT and not (
        template.first_message_text or ""
    ).strip():
        raise BusinessRuleException(
            "La plantilla de Admin no tiene saludo inicial y no puede aplicarse."
        )

    from src.application.ai.process_prompt_resolver import next_process_prompt_version
    from src.infrastructure.db.audit import record_audit

    active_rows = (
        (
            await db.execute(
                select(ProcessAIPrompt).where(
                    ProcessAIPrompt.process_id == process_id,
                    ProcessAIPrompt.task_type == task_type.value,
                    ProcessAIPrompt.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
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
        first_message_text=(
            template.first_message_text if task_type == AITaskType.VOICE_CALL_AGENT else None
        ),
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
        .options(
            selectinload(HiringProcess.job_descriptions),
            selectinload(HiringProcess.process_candidates),
        )
    )
    process: HiringProcess | None = result.scalar_one_or_none()

    if not process:
        raise NotFoundException("Proceso no encontrado")

    if process.status in (ProcessStatus.CLOSED.value, ProcessStatus.ARCHIVED.value):
        raise BusinessRuleException("RB-009: Proceso cerrado o archivado")

    # Versión incremental
    is_first_version = not process.job_descriptions
    next_version = max((jd.version for jd in process.job_descriptions), default=0) + 1

    jd = JobDescription(
        process_id=process_id,
        version=next_version,
        jd_raw_text=body.jd_raw_text,
        structured_jd={"version": next_version, "raw": body.jd_raw_text},
    )
    db.add(jd)

    # El JD cambió: el match/ranking anterior quedó obsoleto. Solo se revierten los
    # candidatos ya matcheados (MATCHED); los que avanzaron a profiling no se tocan.
    if not is_first_version:
        for pc in process.process_candidates:
            if pc.status == CandidateStatus.MATCHED.value:
                pc.status = CandidateStateMachine.transition(
                    CandidateStatus.MATCHED, CandidateStatus.MATCH_PENDING
                ).value
                pc.match_percentage = 0.00
                pc.match_category = None
                pc.match_explanation = None

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
