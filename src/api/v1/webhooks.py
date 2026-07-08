import asyncio
import hashlib
import hmac
import logging
import uuid
from datetime import UTC, datetime
from functools import partial
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.candidate.whatsapp_message_usecase import ProcessWhatsAppMessageUseCase
from src.application.profiling.voice_config_resolver import resolve_voice_config
from src.config import settings
from src.domain.candidate.state_machine import CandidateStateMachine
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    Candidate,
    CandidateStatus,
    CostLog,
    HiringProcess,
    OperationType,
    ProcessCandidate,
    ProfilingRun,
    ProfilingRunStatus,
)
from src.infrastructure.voice import elevenlabs_client, twilio_client
from src.infrastructure.workers.tasks.profiling import (
    evaluate_profiling_transcription,
    retry_or_fail_profiling_call,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# Créditos ElevenLabs -> USD, aproximado (400 créditos ~= 1 minuto en plan Creator).
_ELEVENLABS_CREDITS_PER_USD_MINUTE = 400
_ELEVENLABS_USD_PER_MINUTE_DEFAULT = 0.09


def _verify_meta_signature(payload: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        settings.meta_whatsapp_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _extract_message_content(message: dict) -> tuple[str, str]:
    """
    Extrae (from_phone, text) de cualquier tipo de mensaje de WhatsApp.

    Tipos que manejamos:
    - text            → mensaje de texto libre del candidato
    - interactive     → clic en botón de la plantilla (button_reply)
    """
    from_phone = message.get("from", "")
    msg_type = message.get("type", "")

    if msg_type == "text":
        return from_phone, message.get("text", {}).get("body", "")

    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        if interactive.get("type") == "button_reply":
            # El candidato hizo clic en "Sí, acepto" o "No, gracias"
            return from_phone, interactive["button_reply"]["title"]

    return from_phone, ""


@router.get("/whatsapp")
async def verify_whatsapp_webhook(request: Request) -> Response:
    """Meta llama aquí para verificar el webhook al configurarlo."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.meta_whatsapp_verify_token:
        return Response(content=challenge, status_code=200)

    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@router.post("/whatsapp")
async def receive_whatsapp_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Recibe mensajes y clics de botón de WhatsApp, valida firma HMAC de Meta."""
    raw_body = await request.body()

    if settings.app_env != "development":
        if not _verify_meta_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(status_code=403, detail="Firma HMAC inválida")

    body = await request.json()

    if body.get("object") != "whatsapp_business_account":
        raise HTTPException(status_code=404, detail="No es un evento de WhatsApp")

    use_case = ProcessWhatsAppMessageUseCase(db)

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "messages" not in value:
                continue
            for message in value["messages"]:
                from_phone, text = _extract_message_content(message)
                if from_phone and text:
                    await use_case.execute(from_phone, text)

    return {"status": "ok"}


_TWIML_HANGUP = '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
_MACHINE_ANSWERED_BY = {
    "machine_start",
    "machine_end_beep",
    "machine_end_silence",
    "machine_end_other",
    "fax",
}
_NO_CONNECT_CALL_STATUSES = {"no-answer", "busy", "failed", "canceled"}


def _build_twilio_webhook_url(request: Request) -> str:
    """Reconstruye la URL publica exacta que Twilio invoco (para verificar su firma),
    ya que request.url puede reflejar el host interno si hay un proxy/ngrok delante."""
    base = settings.public_base_url.rstrip("/")
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{base}{request.url.path}{query}"


def _form_to_str_dict(form: Any) -> dict[str, str]:
    return {k: str(v) for k, v in form.items()}


async def _get_run_or_none(db: AsyncSession, run_id: str) -> ProfilingRun | None:
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="run_id invalido")
    return await db.get(ProfilingRun, run_uuid)


def _build_dynamic_variables(
    pc: ProcessCandidate, process: HiringProcess, candidate: Candidate
) -> dict[str, str]:
    return {
        "candidate_name": f"{candidate.name} {candidate.last_name}".strip(),
        "job_title": process.job_title,
        "process_id": str(process.id),
    }


@router.post("/twilio/twiml")
async def twilio_twiml_webhook(
    request: Request, run_id: str, db: AsyncSession = Depends(get_db)
) -> Response:
    """
    Webhook que Twilio invoca tras Answering Machine Detection sincrono, pidiendo el
    TwiML a responder. Si AMD detecto maquina -> cuelga y reintenta. Si contesto un
    humano -> registra la llamada en ElevenLabs (register_call) inyectando el system
    prompt/voz resueltos dinamicamente, y devuelve el TwiML que arma el propio SDK.
    """
    form = await request.form()
    signature = request.headers.get("X-Twilio-Signature")
    url = _build_twilio_webhook_url(request)
    valid = await asyncio.to_thread(
        partial(twilio_client.validate_twilio_signature, url, _form_to_str_dict(form), signature)
    )
    if not valid:
        raise HTTPException(status_code=403, detail="Firma de Twilio invalida")

    answered_by = form.get("AnsweredBy")
    call_sid = str(form.get("CallSid", ""))
    to_number = str(form.get("To", ""))

    # Una sola consulta con eager-load de todo lo necesario — Twilio ya viene de esperar
    # el analisis de AMD, cada round-trip adicional a Supabase aqui es silencio en vivo
    # para quien contesto la llamada.
    result = await db.execute(
        select(ProfilingRun)
        .where(ProfilingRun.id == uuid.UUID(run_id))
        .options(
            selectinload(ProfilingRun.question_set),
            selectinload(ProfilingRun.process_candidate).selectinload(ProcessCandidate.candidate),
            selectinload(ProfilingRun.process_candidate).selectinload(ProcessCandidate.process),
        )
    )
    profiling_run = result.scalar_one_or_none()
    if not profiling_run:
        logger.error(f"[twilio][twiml] ProfilingRun {run_id} no encontrado")
        return Response(content=_TWIML_HANGUP, media_type="application/xml")

    if answered_by in _MACHINE_ANSWERED_BY or answered_by in (None, "unknown"):
        profiling_run.status = ProfilingRunStatus.VOICEMAIL_DETECTED.value
        profiling_run.amd_result = str(answered_by or "unknown")
        await db.commit()
        retry_or_fail_profiling_call.delay(str(profiling_run.id), f"AMD:{answered_by}")
        return Response(content=_TWIML_HANGUP, media_type="application/xml")

    # Humano: resolver la config de voz efectiva y registrar la llamada en ElevenLabs.
    profiling_run.status = ProfilingRunStatus.ANSWERED.value
    profiling_run.amd_result = str(answered_by)
    pc = profiling_run.process_candidate
    process = pc.process if pc else None
    question_set = profiling_run.question_set
    candidate = pc.candidate if pc else None

    if not (pc and process and question_set and candidate):
        logger.error(f"[twilio][twiml] datos incompletos para ProfilingRun {run_id}")
        await db.commit()
        return Response(content=_TWIML_HANGUP, media_type="application/xml")

    voice_config = resolve_voice_config(question_set, process)
    dynamic_variables = _build_dynamic_variables(pc, process, candidate)

    try:
        twiml = await asyncio.to_thread(
            partial(
                elevenlabs_client.register_call,
                voice_config,
                dynamic_variables,
                to_number,
                call_sid,
            )
        )
    except Exception as exc:
        logger.error(f"[elevenlabs] register_call fallo para run {run_id}: {exc}")
        await db.commit()
        return Response(content=_TWIML_HANGUP, media_type="application/xml")

    await db.commit()
    return Response(content=twiml, media_type="application/xml")


@router.post("/twilio/status")
async def twilio_status_webhook(
    request: Request, run_id: str, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """
    Captura llamadas que nunca llegaron a /twiml (no-answer/busy/failed/canceled) —
    la unica forma de saber que una llamada jamas conecto, ya que AMD no llega a correr.
    """
    form = await request.form()
    signature = request.headers.get("X-Twilio-Signature")
    url = _build_twilio_webhook_url(request)
    valid = await asyncio.to_thread(
        partial(twilio_client.validate_twilio_signature, url, _form_to_str_dict(form), signature)
    )
    if not valid:
        raise HTTPException(status_code=403, detail="Firma de Twilio invalida")

    call_status = str(form.get("CallStatus", ""))
    call_sid = str(form.get("CallSid", ""))

    if call_status not in _NO_CONNECT_CALL_STATUSES:
        return {"status": "ignored"}

    profiling_run = await _get_run_or_none(db, run_id)
    if not profiling_run:
        return {"status": "ignored"}

    # Idempotencia: si /twiml ya proceso esta llamada (AMD corrio) o ya se reintento
    # con un CallSid nuevo, este evento de /status ya quedo obsoleto.
    if profiling_run.twilio_call_sid != call_sid:
        return {"status": "ignored"}
    if profiling_run.status != ProfilingRunStatus.CALLING.value:
        return {"status": "ignored"}

    profiling_run.status = ProfilingRunStatus.VOICEMAIL_DETECTED.value
    profiling_run.twilio_status_detail = call_status
    await db.commit()
    retry_or_fail_profiling_call.delay(str(profiling_run.id), f"status:{call_status}")
    return {"status": "ok"}


def _estimate_elevenlabs_cost_usd(metadata: dict[str, Any]) -> float:
    credits = metadata.get("cost", 0) or 0
    usd_per_minute = _ELEVENLABS_USD_PER_MINUTE_DEFAULT
    return round((credits / _ELEVENLABS_CREDITS_PER_USD_MINUTE) * usd_per_minute, 6)


@router.post("/elevenlabs/post-call-transcription")
async def elevenlabs_post_call_webhook(
    request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Webhook nativo de plataforma de ElevenLabs (post_call_transcription), configurado
    aparte en su dashboard. Trae transcript/resumen/costo de la conversacion, y se
    correlaciona con nuestro ProfilingRun via el twilio_call_sid que inyectamos como
    dynamic_variable al registrar la llamada.
    """
    raw_body = await request.body()
    sig_header = request.headers.get("ElevenLabs-Signature")
    try:
        payload = await asyncio.to_thread(
            partial(
                elevenlabs_client.verify_webhook_signature,
                raw_body.decode("utf-8"),
                sig_header,
            )
        )
    except Exception as exc:
        logger.warning(f"[elevenlabs][post-call] firma invalida: {exc}")
        raise HTTPException(status_code=403, detail="Firma de ElevenLabs invalida")

    data = payload.get("data", payload)
    conversation_id = data.get("conversation_id")
    client_data = data.get("conversation_initiation_client_data", {}) or {}
    dynamic_variables = client_data.get("dynamic_variables", {}) or {}
    twilio_call_sid = dynamic_variables.get("twilio_call_sid")

    profiling_run = None
    if twilio_call_sid:
        result = await db.execute(
            select(ProfilingRun)
            .where(ProfilingRun.twilio_call_sid == twilio_call_sid)
            .with_for_update()
        )
        profiling_run = result.scalar_one_or_none()
    if not profiling_run and conversation_id:
        result = await db.execute(
            select(ProfilingRun)
            .where(ProfilingRun.elevenlabs_conversation_id == conversation_id)
            .with_for_update()
        )
        profiling_run = result.scalar_one_or_none()

    if not profiling_run:
        logger.error(f"[elevenlabs][post-call] no se pudo correlacionar conv_id={conversation_id}")
        return {"status": "ignored"}

    if profiling_run.status == ProfilingRunStatus.COMPLETED.value:
        return {"status": "ok", "idempotent": True}

    analysis = data.get("analysis", {}) or {}
    metadata = data.get("metadata", {}) or {}
    transcript = data.get("transcript", "")

    profiling_run.elevenlabs_conversation_id = conversation_id
    profiling_run.transcript_summary = analysis.get("transcript_summary")
    profiling_run.status = ProfilingRunStatus.COMPLETED.value
    profiling_run.completed_at = datetime.now(UTC)

    pc = await db.get(ProcessCandidate, profiling_run.process_candidate_id)
    if pc:
        try:
            pc.status = CandidateStateMachine.transition(
                CandidateStatus(pc.status), CandidateStatus.PROFILING_COMPLETED
            )
        except BusinessRuleException as exc:
            logger.warning(f"[elevenlabs][post-call] transicion invalida para {pc.id}: {exc}")

    db.add(
        CostLog(
            process_id=pc.process_id if pc else None,
            candidate_id=pc.candidate_id if pc else None,
            operation_type=OperationType.VOICE_CALL.value,
            model_used="elevenlabs-conversational-ai",
            call_duration_s=int(metadata.get("call_duration_secs", 0) or 0),
            estimated_cost=_estimate_elevenlabs_cost_usd(metadata),
        )
    )

    await db.commit()

    evaluate_profiling_transcription.delay(str(profiling_run.id), transcript)
    return {"status": "ok"}

