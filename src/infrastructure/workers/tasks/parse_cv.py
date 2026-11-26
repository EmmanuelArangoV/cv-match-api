"""
Tarea Celery: descarga el CV de R2, extrae el contenido según el tipo de archivo
(PDF → imágenes vía PyMuPDF, DOCX → texto + imágenes embebidas, imágenes → directo),
llama al modelo OpenAI activo con visión para extraer el perfil estructurado, genera el PDF
normalizado
en estilo BBLABS y lo sube a R2.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import unicodedata
import uuid
import zipfile
from collections.abc import Callable
from typing import Any

import pymupdf as fitz  # PyMuPDF >= 1.24
from openai import BadRequestError, OpenAI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.application.hiring_process.progress import sync_process_status_sync
from src.config import settings
from src.infrastructure.ai.model_compat import DEFAULT_OPENAI_MODEL, chat_completion_options
from src.infrastructure.costs import (
    calculate_openai_cost,
    calculate_r2_cost,
    extract_openai_usage,
    record_cost_sync,
)
from src.infrastructure.cv.pdf_renderer import extract_jd_highlight_terms, render_normalized_cv
from src.infrastructure.storage.r2_client import download_file_sync, upload_file_sync
from src.infrastructure.workers.celery_app import celery_app

_engine = create_engine(settings.database_url_sync)
_SyncSession = sessionmaker(bind=_engine)
logger = logging.getLogger(__name__)


class CVResponseError(ValueError):
    def __init__(self, reason: str, response: object, *, retryable: bool = True) -> None:
        super().__init__(reason)
        self.reason = reason
        self.response = response
        self.retryable = retryable


def _parse_response(response: object, model: str, stage: str) -> dict[str, Any]:
    choices = getattr(response, "choices", None) or []
    choice = choices[0] if choices else None
    message = getattr(choice, "message", None)
    finish_reason = getattr(choice, "finish_reason", None)
    content = getattr(message, "content", None)
    logger.info(
        "CV response stage=%s model=%s response_id=%s finish_reason=%s usage=%s",
        stage, model, getattr(response, "id", None), finish_reason,
        extract_openai_usage(response),
    )
    if getattr(message, "refusal", None) or finish_reason == "content_filter":
        raise CVResponseError("Respuesta rechazada por el proveedor", response, retryable=False)
    if finish_reason == "length":
        raise CVResponseError("Respuesta truncada", response)
    if not content or not content.strip():
        raise CVResponseError("Respuesta vacía", response)
    try:
        result = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise CVResponseError("Respuesta JSON inválida", response) from exc
    if not isinstance(result, dict) or not result:
        raise CVResponseError("Respuesta JSON sin perfil", response)
    return result

# Extensiones reconocidas como imágenes directas
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tiff", ".tif", ".bmp"}
_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
}


def _get_openai() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


# ─── Extractores por formato ───────────────────────────────────────────────────


def _pdf_to_content(pdf_bytes: bytes) -> list[dict]:
    """Convierte cada página del PDF a un bloque image_url para la API de visión."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    items: list[dict] = []
    for page in doc:
        mat = fitz.Matrix(2.0, 2.0)  # zoom 2× para mejor resolución
        pix = page.get_pixmap(matrix=mat)
        b64 = base64.b64encode(pix.tobytes("png")).decode()
        items.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
            }
        )
    doc.close()
    return items


def _docx_to_content(docx_bytes: bytes) -> list[dict]:
    """
    Extrae texto e imágenes embebidas de un DOCX.
    Devuelve bloques listos para la API de OpenAI:
      - un bloque 'text' con todo el texto plano del documento
      - un bloque 'image_url' por cada imagen embebida (hasta 10)
    """
    from docx import Document  # python-docx

    doc = Document(io.BytesIO(docx_bytes))
    items: list[dict] = []

    # ── Texto plano ──────────────────────────────────────────────────────────
    lines: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            lines.append(text)
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
            if row_text:
                lines.append(row_text)

    if lines:
        items.append({"type": "text", "text": "DOCUMENTO (texto extraído):\n" + "\n".join(lines)})

    # ── Imágenes embebidas en el zip del DOCX ────────────────────────────────
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/") and not n.endswith("/")]
            for name in media[:10]:  # limitamos a 10 imágenes por documento
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                mime = _IMAGE_MIME.get(ext)
                if not mime:
                    continue
                b64 = base64.b64encode(z.read(name)).decode()
                items.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
                    }
                )
    except Exception:
        pass  # si falla la extracción de imágenes, continuamos solo con texto

    return items


def _image_to_content(image_bytes: bytes, ext: str) -> list[dict]:
    """Encoda una imagen directamente como bloque image_url."""
    mime = _IMAGE_MIME.get(ext, "image/jpeg")
    b64 = base64.b64encode(image_bytes).decode()
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
        }
    ]


def _prepare_content(file_bytes: bytes, r2_key: str) -> list[dict]:
    """Devuelve la lista de bloques de contenido según el tipo de archivo."""
    ext = ""
    if "." in r2_key:
        ext = "." + r2_key.rsplit(".", 1)[-1].lower()

    if ext == ".docx" or ext == ".doc":
        return _docx_to_content(file_bytes)
    if ext in _IMAGE_EXTS:
        return _image_to_content(file_bytes, ext)
    # Por defecto (PDF u otros): intentar como PDF
    return _pdf_to_content(file_bytes)


# ─── Llamada a OpenAI ──────────────────────────────────────────────────────────


def _get_embedding(text: str, client: OpenAI) -> tuple[list[float], int]:
    """Genera un vector embedding para el texto dado."""
    response = client.embeddings.create(input=text, model="text-embedding-3-small")
    tokens_in = int(getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0)
    # CreateEmbeddingResponse no incluye un id de proveedor. La referencia
    # idempotente se construye en la tarea a partir del intento de Celery.
    return response.data[0].embedding, tokens_in


def _call_openai(
    content_blocks: list[dict], client: OpenAI, prompt: str, model: str, *, max_tokens: int = 4096,
    on_response: Callable[[object], None] | None = None,
) -> tuple[dict, int, int, int, int, int, str]:
    content: list[dict] = [{"type": "text", "text": prompt}]
    content.extend(content_blocks)

    response = client.chat.completions.create(  # type: ignore[call-overload]
        model=model,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        **chat_completion_options(model, max_tokens=max_tokens),
    )

    if on_response:
        on_response(response)
    result = _parse_response(response, model, "CV_EXTRACTION")
    tokens_in, tokens_out, cached_tokens, cache_write_tokens, reasoning_tokens = (
        extract_openai_usage(response)
    )
    return (
        result,
        tokens_in,
        tokens_out,
        cached_tokens,
        cache_write_tokens,
        reasoning_tokens,
        str(response.id),
    )


def _profile_source_language(profile: dict[str, object]) -> str:
    """Estimación conservadora para evitar traducir dos veces un mismo CV."""
    text = json.dumps(profile, ensure_ascii=False).casefold()
    spanish_markers = (" experiencia", " habilidades", " desarrollo", " trabajo", " empresa")
    english_markers = (" experience", " skills", " development", " work", " company")
    spanish_score = sum(text.count(marker) for marker in spanish_markers)
    english_score = sum(text.count(marker) for marker in english_markers)
    return "es" if spanish_score >= english_score else "en"


def _normalized_cv_filename(language: str, candidate_name: object, job_title: object) -> str:
    """Construye un nombre descargable, portable y sin datos de contacto."""

    def _component(value: object, fallback: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:80]
        return slug or fallback

    prefix = "ES" if language == "es" else "EN"
    return f"{prefix}_{_component(candidate_name, 'Candidato')}_{_component(job_title, 'Rol')}.pdf"


def _call_translation_openai(
    profile: dict[str, object], client: OpenAI, prompt: str, model: str, target_language: str,
    *, max_tokens: int = 4096, on_response: Callable[[object], None] | None = None,
) -> tuple[dict[str, object], int, int, int, int, int, str]:
    """Hace exactamente una llamada adicional para construir el segundo idioma."""
    target_name = "Spanish" if target_language == "es" else "English"
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\nTARGET LANGUAGE: {target_name}\n\n"
                    "NORMALIZED CV JSON:\n"
                    f"{json.dumps(profile, ensure_ascii=False)}"
                ),
            }
        ],
        response_format={"type": "json_object"},
        **chat_completion_options(model, max_tokens=max_tokens),
    )
    if on_response:
        on_response(response)
    translated = _parse_response(response, model, "CV_TRANSLATION")
    tokens_in, tokens_out, cached_tokens, cache_write_tokens, reasoning_tokens = (
        extract_openai_usage(response)
    )
    return (
        translated,
        tokens_in,
        tokens_out,
        cached_tokens,
        cache_write_tokens,
        reasoning_tokens,
        str(response.id),
    )


def _build_extraction_prompt(prompt: str, analysis_context: str | None) -> str:
    """Añade el comentario del recruiter al prompt sin alterar el prompt configurable.

    OJO: la regla #2 del prompt base ("Never invent or guess data") es la primera
    instrucción fuerte que ve el modelo, y compite directamente con "usa esta nota
    como fuente prioritaria" si no se aclara explícitamente la excepción — el modelo
    tiende a tratar cualquier dato que no esté en el CV como una "invención" y
    descarta la corrección del recruiter en vez de aplicarla. Por eso el bloque de
    abajo nombra la regla #2 y aclara que esta nota no cae en esa categoría.
    """
    context = (analysis_context or "").strip()
    if not context:
        return prompt

    return f"""{prompt}

=== INFORMACIÓN ADICIONAL DEL RECRUITER (verificada, no es una suposición) ===
{context}

Esta nota es una corrección verificada por el reclutador, no una invención ni una
suposición del modelo — la regla "Never invent or guess data" NO aplica a los datos
de identidad o contacto que esta nota corrija o complete explícitamente (ej. nombre,
teléfono, email, ubicación). Cuando esta nota contradiga o complete lo que aparece
en el CV para esos campos, usa el valor de la nota, no el del CV. Para el resto de
los campos del esquema (experiencia, educación, skills, etc.), sigue basándote
únicamente en el contenido del CV.
"""


# ─── Tarea Celery ──────────────────────────────────────────────────────────────


def _parse_cv(
    self: Any,
    candidate_id: str,
    process_candidate_id: str,
    process_id: str,
) -> dict[str, Any]:
    from src.domain.candidate.state_machine import CandidateStateMachine
    from src.infrastructure.db.models import (
        Candidate,
        CandidateCVVersion,
        CandidateStatus,
        CostLog,
        HiringProcess,
        JobDescription,
        OperationType,
        ProcessCandidate,
    )

    uuid.UUID(candidate_id)
    pc_uuid = uuid.UUID(process_candidate_id)
    proc_uuid = uuid.UUID(process_id)
    stage = "CV_EXTRACTION"
    model = DEFAULT_OPENAI_MODEL

    with _SyncSession() as db:
        try:
            pc: ProcessCandidate = db.get(ProcessCandidate, pc_uuid)
            candidate: Candidate | None = db.get(Candidate, pc.candidate_id) if pc else None
            cv_version: CandidateCVVersion | None = (
                db.get(CandidateCVVersion, pc.cv_version_id) if pc else None
            )

            if not candidate or not pc or not cv_version:
                return {"error": "Candidate, ProcessCandidate or CV version not found"}

            db.refresh(pc, attribute_names=["status", "cv_task_id"], with_for_update=True)
            if (pc.process_id != proc_uuid
                    or pc.status != CandidateStatus.CV_PROCESSING.value
                    or pc.cv_task_id != self.request.id):
                return {"skipped": "CV analysis claim is no longer current"}

            # Descargar el archivo de R2
            file_bytes = download_file_sync(cv_version.original_file_url)

            # Preparar bloques de contenido según el tipo de archivo
            content_blocks = _prepare_content(file_bytes, cv_version.original_file_url)

            if not content_blocks:
                raise ValueError(
                    f"No se pudo extraer contenido del archivo: {cv_version.original_file_url}"
                )

            # Llamar a OpenAI
            openai_client = _get_openai()
            from src.application.ai.process_prompt_resolver import get_effective_prompt_sync
            from src.infrastructure.cache.redis_client import get_active_ai_model_sync

            prompt = get_effective_prompt_sync(db, proc_uuid, "CV_EXTRACTION").system_prompt_text
            prompt = _build_extraction_prompt(prompt, pc.analysis_context)
            model = get_active_ai_model_sync(db, "CV_EXTRACTION", "OPENAI", DEFAULT_OPENAI_MODEL)
            process = db.get(HiringProcess, proc_uuid)

            def record_response(response: object) -> None:
                assert candidate is not None
                usage = extract_openai_usage(response)
                cost = calculate_openai_cost(model, *usage)
                response_id = getattr(response, "id", None)
                if not response_id:
                    raise ValueError("La respuesta de OpenAI no tiene identificador")
                with _SyncSession() as cost_db:
                    record_cost_sync(
                        cost_db,
                        process_id=proc_uuid,
                        candidate_id=candidate.id,
                        user_id=process.recruiter_id if process else None,
                        operation_type=stage,
                        provider="OPENAI",
                        model_used=model,
                        tokens_input=usage[0],
                        tokens_cached=usage[2],
                        tokens_output=usage[1],
                        estimated_cost=cost.amount_usd,
                        cost_source=cost.source,
                        external_reference=f"openai:{response_id}",
                        cost_breakdown=cost.breakdown,
                    )
                    cost_db.commit()

            (
                extracted,
                tokens_in,
                tokens_out,
                cached_tokens,
                cache_write_tokens,
                reasoning_tokens,
                response_id,
            ) = _call_openai(
                content_blocks, openai_client, prompt, model,
                max_tokens=8192 if self.request.retries else 4096,
                on_response=record_response,
            )

            # Deduplicación por correo. La identidad global puede cambiar, pero
            # el CV recién extraído conserva su propia versión y objeto en R2.
            # Nunca se sobrescribe el perfil de la identidad existente.
            merged_into_existing_candidate = False
            ext_email = extracted.get("email")
            if ext_email and "@placeholder" in candidate.email:
                existing = db.query(Candidate).filter(Candidate.email == ext_email).first()
                if existing:
                    temporary_candidate_id = candidate.id
                    pc.candidate_id = existing.id
                    cv_version.candidate_id = existing.id
                    db.flush()
                    # El upload original ya puede haber dejado un costo contra el
                    # candidato temporal. Conservamos su atribución al consolidar.
                    db.query(CostLog).filter(CostLog.candidate_id == temporary_candidate_id).update(
                        {CostLog.candidate_id: existing.id}, synchronize_session=False
                    )
                    try:
                        db.delete(candidate)
                    except Exception:
                        pass
                    candidate = existing
                    merged_into_existing_candidate = True
                else:
                    candidate.email = ext_email

            process = db.get(HiringProcess, proc_uuid)
            extraction_cost = calculate_openai_cost(
                model,
                tokens_in,
                tokens_out,
                cached_tokens,
                cache_write_tokens,
                reasoning_tokens,
            )
            # La deduplicación puede haber actualizado el candidato y conserva un lock
            # incompatible con la FK de cost_logs. Confirmamos ese cambio antes de abrir
            # la transacción independiente; así el costo facturado se conserva aunque
            # falle el render/subida posterior, sin esperar al statement_timeout.
            db.commit()
            db.refresh(pc, attribute_names=["status", "cv_task_id"], with_for_update=True)
            if (pc.status != CandidateStatus.CV_PROCESSING.value
                    or pc.cv_task_id != self.request.id):
                db.rollback()
                return {"skipped": "CV analysis claim is no longer current"}
            with _SyncSession() as cost_db:
                record_cost_sync(
                    cost_db,
                    process_id=proc_uuid,
                    candidate_id=candidate.id,
                    user_id=process.recruiter_id if process else None,
                    operation_type=OperationType.CV_EXTRACTION.value,
                    provider="OPENAI",
                    model_used=model,
                    tokens_input=tokens_in,
                    tokens_cached=cached_tokens,
                    tokens_output=tokens_out,
                    estimated_cost=extraction_cost.amount_usd,
                    cost_source=extraction_cost.source,
                    external_reference=f"openai:{response_id}",
                    cost_breakdown=extraction_cost.breakdown,
                )
                cost_db.commit()

            # Perfil y artefactos pertenecen a la versión del CV, no a Candidate.
            cv_version.extracted_profile = extracted

            # Se mantiene el idioma extraído y se construye solo su contraparte: una
            # llamada pagada adicional por CV, auditada de forma independiente.
            source_language = _profile_source_language(extracted)
            translation_prompt = get_effective_prompt_sync(
                db, proc_uuid, "CV_TRANSLATION"
            ).system_prompt_text
            translation_model = get_active_ai_model_sync(db, "CV_TRANSLATION", "OPENAI", model)
            stage = "CV_TRANSLATION"
            model = translation_model
            target_language = "en" if source_language == "es" else "es"
            (
                translated_profile,
                translation_tokens_in,
                translation_tokens_out,
                translation_cached_tokens,
                translation_cache_write_tokens,
                translation_reasoning_tokens,
                translation_response_id,
            ) = _call_translation_openai(
                extracted,
                openai_client,
                translation_prompt,
                translation_model,
                target_language,
                max_tokens=8192 if self.request.retries else 4096,
                on_response=record_response,
            )
            translation_cost = calculate_openai_cost(
                translation_model,
                translation_tokens_in,
                translation_tokens_out,
                translation_cached_tokens,
                translation_cache_write_tokens,
                translation_reasoning_tokens,
            )
            with _SyncSession() as cost_db:
                record_cost_sync(
                    cost_db,
                    process_id=proc_uuid,
                    candidate_id=candidate.id,
                    user_id=process.recruiter_id if process else None,
                    operation_type=OperationType.CV_TRANSLATION.value,
                    provider="OPENAI",
                    model_used=translation_model,
                    tokens_input=translation_tokens_in,
                    tokens_cached=translation_cached_tokens,
                    tokens_output=translation_tokens_out,
                    estimated_cost=translation_cost.amount_usd,
                    cost_source=translation_cost.source,
                    external_reference=f"openai:{translation_response_id}",
                    cost_breakdown=translation_cost.breakdown,
                )
                cost_db.commit()

            spanish_profile = extracted if source_language == "es" else translated_profile
            english_profile = extracted if source_language == "en" else translated_profile
            # Español es la representación canónica existente para no cambiar el
            # comportamiento del match ni los consumidores que leen normalized_cv.
            cv_version.normalized_cv = spanish_profile

            # Generar Embedding para búsqueda semántica
            try:
                profile_text = json.dumps(extracted, ensure_ascii=False)
                embedding, embedding_tokens = _get_embedding(profile_text, openai_client)
                cv_version.cv_embedding = embedding
                embedding_cost = calculate_openai_cost("text-embedding-3-small", embedding_tokens)
                task_reference = self.request.id or str(uuid.uuid4())
                retry_number = int(getattr(self.request, "retries", 0) or 0)
                with _SyncSession() as cost_db:
                    record_cost_sync(
                        cost_db,
                        process_id=proc_uuid,
                        candidate_id=candidate.id,
                        user_id=process.recruiter_id if process else None,
                        operation_type=OperationType.CV_EMBEDDING.value,
                        provider="OPENAI",
                        model_used="text-embedding-3-small",
                        tokens_input=embedding_tokens,
                        estimated_cost=embedding_cost.amount_usd,
                        cost_source="openai_rate_card_no_provider_id",
                        external_reference=(f"openai-embedding:{task_reference}:{retry_number}"),
                        cost_breakdown={
                            **embedding_cost.breakdown,
                            "provider_reference_available": False,
                            "task_reference": task_reference,
                            "retry_number": retry_number,
                        },
                    )
                    cost_db.commit()
            except Exception as exc:
                # El embedding no bloquea la extracción, pero no debe fallar en silencio:
                # su ausencia afecta búsqueda semántica y puede ocultar consumo facturado.
                logger.warning(
                    "[parse_cv] embedding no persistido para candidate=%s: %s",
                    candidate.id,
                    exc,
                )

            # La identidad se completa solo para un candidato nuevo. Si el correo
            # consolidó con una identidad existente, B no reemplaza los datos de A.
            if not merged_into_existing_candidate:
                full_name: str = extracted.get("full_name", "")
                if full_name and " " in full_name:
                    parts = full_name.split(" ", 1)
                    candidate.name = parts[0][:100]
                    candidate.last_name = parts[1][:100]
                elif full_name:
                    candidate.name = full_name[:100]

                if extracted.get("phone"):
                    candidate.phone = extracted["phone"][:20]

            # Generar ambas variantes BBLABS y subirlas a R2.
            active_jd: JobDescription | None = None
            if process:
                active_jd = (
                    db.query(JobDescription)
                    .filter(JobDescription.process_id == proc_uuid)
                    .order_by(JobDescription.version.desc())
                    .first()
                )
            highlight_terms = extract_jd_highlight_terms(
                spanish_profile,
                active_jd.jd_raw_text if active_jd else "",
                active_jd.structured_jd if active_jd else None,
            )
            spanish_pdf_bytes = render_normalized_cv(
                spanish_profile, language="es", highlight_terms=highlight_terms
            )
            english_pdf_bytes = render_normalized_cv(
                english_profile, language="en", highlight_terms=highlight_terms
            )
            # La carpeta por versión evita sobrescribir CVs históricos del mismo candidato.
            # El basename es el que el navegador usa al descargar desde la URL firmada de R2.
            candidate_name = spanish_profile.get("full_name") or (
                f"{candidate.name} {candidate.last_name}"
            )
            job_title = process.job_title if process else "Rol"
            normalized_directory = f"cvs/{proc_uuid}/{cv_version.id}"
            normalized_key_es = (
                f"{normalized_directory}/{_normalized_cv_filename('es', candidate_name, job_title)}"
            )
            normalized_key_en = (
                f"{normalized_directory}/{_normalized_cv_filename('en', candidate_name, job_title)}"
            )
            upload_file_sync(normalized_key_es, spanish_pdf_bytes, "application/pdf")
            upload_file_sync(normalized_key_en, english_pdf_bytes, "application/pdf")
            cv_version.normalized_file_url = normalized_key_es
            cv_version.normalized_file_url_es = normalized_key_es
            cv_version.normalized_file_url_en = normalized_key_en

            storage_cost = calculate_r2_cost(
                bytes_stored=len(spanish_pdf_bytes) + len(english_pdf_bytes),
                class_a_operations=2,
                class_b_operations=2,
            )
            with _SyncSession() as cost_db:
                record_cost_sync(
                    cost_db,
                    process_id=proc_uuid,
                    candidate_id=candidate.id,
                    user_id=process.recruiter_id if process else None,
                    operation_type=OperationType.CV_STORAGE.value,
                    provider="CLOUDFLARE_R2",
                    model_used="r2-standard-normalized-cv-bilingual",
                    estimated_cost=storage_cost.amount_usd,
                    cost_source=storage_cost.source,
                    external_reference=(
                        "r2-normalize-bilingual:"
                        f"{normalized_key_es}:{self.request.id or uuid.uuid4()}"
                    ),
                    cost_breakdown={
                        **storage_cost.breakdown,
                        "object_keys": [normalized_key_es, normalized_key_en],
                    },
                )
                cost_db.commit()

            # Actualizar estado del proceso-candidato
            pc.status = CandidateStateMachine.transition(
                CandidateStatus(pc.status), CandidateStatus.MATCH_PENDING
            ).value
            pc.cv_task_id = None
            sync_process_status_sync(db, proc_uuid)

            db.commit()

            return {
                "candidate_id": str(candidate.id),
                "status": CandidateStatus.MATCH_PENDING.value,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "estimated_cost_usd": float(extraction_cost.amount_usd),
            }

        except Exception as exc:
            db.rollback()
            if isinstance(exc, CVResponseError):
                logger.warning(
                    "CV response rejected stage=%s model=%s process_candidate=%s task=%s reason=%s",
                    stage, model, pc_uuid, self.request.id, exc.reason,
                )
            # Keep the claim while Celery has another attempt scheduled. Otherwise
            # another analysis request can enqueue the same candidate concurrently.
            retryable = not isinstance(exc, BadRequestError) and (
                not isinstance(exc, CVResponseError) or exc.retryable
            )
            if retryable and self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
            try:
                pc = db.get(ProcessCandidate, pc_uuid)
                if (pc and pc.status == CandidateStatus.CV_PROCESSING.value
                        and pc.cv_task_id == self.request.id):
                    pc.status = CandidateStateMachine.transition(
                        CandidateStatus(pc.status), CandidateStatus.CV_ERROR
                    ).value
                    pc.cv_task_id = None
                    sync_process_status_sync(db, proc_uuid)
                    db.commit()
            except Exception:
                pass
            raise


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60, name="parse_cv")
def parse_cv(
    self: Any, candidate_id: str, process_candidate_id: str, process_id: str
) -> dict[str, Any]:
    # A session advisory lock remains held across the commits made by the task.
    # Duplicate deliveries wait and then observe that the claim has completed.
    with _engine.connect() as lock_connection:
        lock_connection.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"),
            {"key": f"cv-analysis:{process_candidate_id}"},
        )
        try:
            return _parse_cv(self, candidate_id, process_candidate_id, process_id)
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                {"key": f"cv-analysis:{process_candidate_id}"},
            )
