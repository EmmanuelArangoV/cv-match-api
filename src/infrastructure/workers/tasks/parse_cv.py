"""
Tarea Celery: descarga el CV de R2, extrae el contenido según el tipo de archivo
(PDF → imágenes vía PyMuPDF, DOCX → texto + imágenes embebidas, imágenes → directo),
llama a gpt-4o vision para extraer el perfil estructurado, genera el PDF normalizado
en estilo BBLABS y lo sube a R2.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import uuid
import zipfile

import pymupdf as fitz  # PyMuPDF >= 1.24
from openai import OpenAI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.application.hiring_process.progress import sync_process_status_sync
from src.config import settings
from src.infrastructure.ai.prompts import CV_EXTRACTION_PROMPT
from src.infrastructure.costs import (
    calculate_openai_cost,
    calculate_r2_cost,
    extract_openai_usage,
    record_cost_sync,
)
from src.infrastructure.cv.pdf_renderer import render_normalized_cv
from src.infrastructure.storage.r2_client import download_file_sync, upload_file_sync
from src.infrastructure.workers.celery_app import celery_app

_engine = create_engine(settings.database_url_sync)
_SyncSession = sessionmaker(bind=_engine)
logger = logging.getLogger(__name__)

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
    content_blocks: list[dict], client: OpenAI, prompt: str, model: str
) -> tuple[dict, int, int, int, str]:
    content: list[dict] = [{"type": "text", "text": prompt}]
    content.extend(content_blocks)

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        max_tokens=4096,
    )

    result = json.loads(response.choices[0].message.content)
    tokens_in, tokens_out, cached_tokens = extract_openai_usage(response)
    return result, tokens_in, tokens_out, cached_tokens, str(response.id)


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


@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    name="parse_cv",
)
def parse_cv(
    self,
    candidate_id: str,
    process_candidate_id: str,
    process_id: str,
) -> dict:
    from src.infrastructure.db.models import (
        Candidate,
        CandidateStatus,
        HiringProcess,
        OperationType,
        ProcessCandidate,
    )

    cand_uuid = uuid.UUID(candidate_id)
    pc_uuid = uuid.UUID(process_candidate_id)
    proc_uuid = uuid.UUID(process_id)

    with _SyncSession() as db:
        try:
            candidate: Candidate = db.get(Candidate, cand_uuid)
            pc: ProcessCandidate = db.get(ProcessCandidate, pc_uuid)

            if not candidate or not pc:
                return {"error": "Candidate or ProcessCandidate not found"}

            # Marcar en proceso
            pc.status = CandidateStatus.CV_PROCESSING.value
            db.commit()
            sync_process_status_sync(db, proc_uuid)
            db.commit()

            # Descargar el archivo de R2
            file_bytes = download_file_sync(candidate.cv_file_url)

            # Preparar bloques de contenido según el tipo de archivo
            content_blocks = _prepare_content(file_bytes, candidate.cv_file_url)

            if not content_blocks:
                raise ValueError(
                    f"No se pudo extraer contenido del archivo: {candidate.cv_file_url}"
                )

            # Llamar a OpenAI
            openai_client = _get_openai()
            from src.infrastructure.cache.redis_client import (
                get_active_ai_model_sync,
                get_active_ai_prompt_sync,
            )

            prompt = get_active_ai_prompt_sync(db, "CV_EXTRACTION", CV_EXTRACTION_PROMPT)
            prompt = _build_extraction_prompt(prompt, pc.analysis_context)
            model = get_active_ai_model_sync(db, "CV_EXTRACTION", "OPENAI", "gpt-4o")
            extracted, tokens_in, tokens_out, cached_tokens, response_id = _call_openai(
                content_blocks, openai_client, prompt, model
            )

            # Deduplicación por correo. Desde este punto, `candidate` puede ser
            # el registro existente al que se reasignó el ProcessCandidate; todas
            # las escrituras posteriores deben usar ese ID efectivo, no el ID
            # temporal recibido por la tarea.
            ext_email = extracted.get("email")
            if ext_email and "@placeholder" in candidate.email:
                existing = db.query(Candidate).filter(Candidate.email == ext_email).first()
                if existing:
                    # Apuntar al existente y tratar de borrar el temporal
                    pc.candidate_id = existing.id
                    db.flush()
                    try:
                        db.delete(candidate)
                    except Exception:
                        pass
                    candidate = existing
                else:
                    candidate.email = ext_email

            process = db.get(HiringProcess, proc_uuid)
            extraction_cost = calculate_openai_cost(
                model, tokens_in, tokens_out, cached_tokens
            )
            # La deduplicación puede haber actualizado el candidato y conserva un lock
            # incompatible con la FK de cost_logs. Confirmamos ese cambio antes de abrir
            # la transacción independiente; así el costo facturado se conserva aunque
            # falle el render/subida posterior, sin esperar al statement_timeout.
            db.commit()
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

            # Actualizar candidato con datos extraídos
            candidate.extracted_profile = extracted
            candidate.normalized_cv = extracted

            # Generar Embedding para búsqueda semántica
            try:
                profile_text = json.dumps(extracted, ensure_ascii=False)
                embedding, embedding_tokens = _get_embedding(profile_text, openai_client)
                candidate.cv_embedding = embedding
                embedding_cost = calculate_openai_cost(
                    "text-embedding-3-small", embedding_tokens
                )
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
                        external_reference=(
                            f"openai-embedding:{task_reference}:{retry_number}"
                        ),
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

            # Actualizar campos básicos si OpenAI los devolvió
            full_name: str = extracted.get("full_name", "")
            if full_name and " " in full_name:
                parts = full_name.split(" ", 1)
                candidate.name = parts[0][:100]
                candidate.last_name = parts[1][:100]
            elif full_name:
                candidate.name = full_name[:100]

            if extracted.get("phone"):
                candidate.phone = extracted["phone"][:20]

            # Generar PDF normalizado en estilo BBLABS y subirlo a R2
            normalized_pdf_bytes = render_normalized_cv(extracted)
            original_key = candidate.cv_file_url
            # Genera siempre una key _normalized.pdf independientemente de la extensión original
            if "." in original_key.rsplit("/", 1)[-1]:
                normalized_key = original_key.rsplit(".", 1)[0] + "_normalized.pdf"
            else:
                normalized_key = original_key + "_normalized.pdf"
            upload_file_sync(normalized_key, normalized_pdf_bytes, "application/pdf")
            candidate.normalized_cv_url = normalized_key

            storage_cost = calculate_r2_cost(
                bytes_stored=len(normalized_pdf_bytes), class_a_operations=1, class_b_operations=1
            )
            with _SyncSession() as cost_db:
                record_cost_sync(
                    cost_db,
                    process_id=proc_uuid,
                    candidate_id=candidate.id,
                    user_id=process.recruiter_id if process else None,
                    operation_type=OperationType.CV_STORAGE.value,
                    provider="CLOUDFLARE_R2",
                    model_used="r2-standard-normalized-cv",
                    estimated_cost=storage_cost.amount_usd,
                    cost_source=storage_cost.source,
                    external_reference=(
                        f"r2-normalize:{normalized_key}:{self.request.id or uuid.uuid4()}"
                    ),
                    cost_breakdown={**storage_cost.breakdown, "object_key": normalized_key},
                )
                cost_db.commit()

            # Actualizar estado del proceso-candidato
            pc.status = CandidateStatus.MATCH_PENDING.value
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
            try:
                pc = db.get(ProcessCandidate, pc_uuid)
                if pc:
                    pc.status = CandidateStatus.CV_ERROR.value
                    sync_process_status_sync(db, proc_uuid)
                    db.commit()
            except Exception:
                pass
            raise self.retry(exc=exc)
