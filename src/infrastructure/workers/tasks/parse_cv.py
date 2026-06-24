"""
Tarea Celery: descarga el CV de R2, lo parsea con gpt-4o vision,
genera el PDF normalizado en estilo BBLABS y los sube a R2.
"""
from __future__ import annotations

import base64
import json
import uuid

import pymupdf as fitz  # PyMuPDF >= 1.24
from openai import OpenAI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.infrastructure.ai.prompts import CV_EXTRACTION_PROMPT
from src.infrastructure.cv.pdf_renderer import render_normalized_cv
from src.infrastructure.storage.r2_client import download_file_sync, upload_file_sync
from src.infrastructure.workers.celery_app import celery_app

_engine = create_engine(settings.database_url_sync)
_SyncSession = sessionmaker(bind=_engine)


def _get_openai() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)

# Costo estimado gpt-4o (USD por token)
_INPUT_COST = 0.0000025
_OUTPUT_COST = 0.000010


def _pdf_to_images(pdf_bytes: bytes) -> list[str]:
    """Convierte cada página del PDF a PNG en base64."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images: list[str] = []
    for page in doc:
        mat = fitz.Matrix(2.0, 2.0)  # zoom 2x para mejor calidad
        pix = page.get_pixmap(matrix=mat)
        images.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return images


def _call_openai(images_b64: list[str], client: OpenAI) -> tuple[dict, int, int]:
    """Llama a gpt-4o vision y retorna (resultado_json, tokens_in, tokens_out)."""
    content: list[dict] = [{"type": "text", "text": CV_EXTRACTION_PROMPT}]
    for b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
        })

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        max_tokens=4096,
    )

    result = json.loads(response.choices[0].message.content)
    return result, response.usage.prompt_tokens, response.usage.completion_tokens


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
        CostLog,
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

            # Descargar PDF de R2
            pdf_bytes = download_file_sync(candidate.cv_file_url)

            # Convertir a imágenes
            images_b64 = _pdf_to_images(pdf_bytes)

            # Llamar a OpenAI
            extracted, tokens_in, tokens_out = _call_openai(images_b64, _get_openai())

            # Actualizar candidato con datos extraídos
            candidate.extracted_profile = extracted
            candidate.normalized_cv = extracted

            # Actualizar campos básicos si OpenAI los devolvió
            full_name: str = extracted.get("full_name", "")
            if full_name and " " in full_name:
                parts = full_name.split(" ", 1)
                candidate.name = parts[0][:100]
                candidate.last_name = parts[1][:100]
            elif full_name:
                candidate.name = full_name[:100]

            if extracted.get("email") and "@placeholder" in candidate.email:
                candidate.email = extracted["email"]

            if extracted.get("phone"):
                candidate.phone = extracted["phone"][:20]

            # Generar PDF normalizado en estilo BBLABS y subirlo a R2
            normalized_pdf_bytes = render_normalized_cv(extracted)
            # Construye la key derivando de la original, ej: cvs/abc123.pdf → cvs/abc123_normalized.pdf
            original_key = candidate.cv_file_url
            if original_key.endswith(".pdf"):
                normalized_key = original_key[:-4] + "_normalized.pdf"
            else:
                normalized_key = original_key + "_normalized.pdf"
            upload_file_sync(normalized_key, normalized_pdf_bytes, "application/pdf")
            candidate.normalized_cv_url = normalized_key

            # Actualizar estado del proceso-candidato
            pc.status = CandidateStatus.MATCH_PENDING.value

            # Registrar costo
            estimated_cost = (tokens_in * _INPUT_COST) + (tokens_out * _OUTPUT_COST)
            cost_log = CostLog(
                process_id=proc_uuid,
                candidate_id=cand_uuid,
                operation_type=OperationType.CV_EXTRACTION.value,
                model_used="gpt-4o",
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                estimated_cost=estimated_cost,
            )
            db.add(cost_log)
            db.commit()

            return {
                "candidate_id": candidate_id,
                "status": "MATCH_PENDING",
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "estimated_cost_usd": round(estimated_cost, 6),
            }

        except Exception as exc:
            db.rollback()
            # Marcar como error para reintento
            try:
                pc = db.get(ProcessCandidate, pc_uuid)
                if pc:
                    pc.status = CandidateStatus.CV_ERROR.value
                    db.commit()
            except Exception:
                pass
            raise self.retry(exc=exc)
