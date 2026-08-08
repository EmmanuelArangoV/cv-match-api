import asyncio
import hashlib
import hmac
import logging
import uuid
from functools import partial
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.candidate.whatsapp_message_usecase import ProcessWhatsAppMessageUseCase
from src.application.profiling.call_context_cache import (
    delete_call_context_sync,
    get_call_context,
    get_prepared_twiml,
    voice_config_from_context,
)
from src.application.profiling.lifecycle import transition_profiling_async
from src.application.profiling.voice_config_resolver import resolve_voice_config
from src.config import settings
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.costs import (
    calculate_elevenlabs_cost,
    calculate_twilio_cost,
    extract_elevenlabs_llm_usage,
    record_cost_async,
)
from src.infrastructure.db.database import AsyncSessionFactory, get_db
from src.infrastructure.db.models import (
    AITaskType,
    Candidate,
    HiringProcess,
    OperationType,
    ProcessCandidate,
    ProfilingRun,
    ProfilingRunStatus,
    QuestionSet,
)
from src.infrastructure.voice import elevenlabs_client, twilio_client
from src.infrastructure.workers.tasks.profiling import (
    evaluate_profiling_transcription,
    retry_or_fail_profiling_call,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

def _verify_meta_signature(payload: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = (
        "sha256="
        + hmac.new(
            settings.meta_whatsapp_webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature_header)


def _extract_message_content(message: dict) -> tuple[str, str]:
    """
    Extrae (from_phone, text) de cualquier tipo de mensaje de WhatsApp.

    Tipos que manejamos:
    - text            → mensaje de texto libre del candidato
    - interactive     → clic en botón de un mensaje interactivo armado por nosotros
    - button          → clic en botón "Quick Reply" de una PLANTILLA aprobada en Meta
                         (nuestro mensaje de consentimiento se envía como "type": "template",
                         no "interactive" — Meta reporta esos clics con este tipo distinto,
                         con el texto en message.button.text en vez de interactive.button_reply)
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

    if msg_type == "button":
        return from_phone, message.get("button", {}).get("text", "")

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
                    try:
                        await use_case.execute(from_phone, text)
                    except Exception as exc:
                        # Meta reintenta (y puede deshabilitar la suscripcion) si
                        # el webhook responde con error — un mensaje problematico
                        # no debe tumbar el resto del batch ni el ack a Meta.
                        logger.error(f"[whatsapp] error procesando mensaje de {from_phone}: {exc}")

    return {"status": "ok"}


_TWIML_HANGUP = '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
_MACHINE_ANSWERED_BY = {
    "machine_start",
    "machine_end_beep",
    "machine_end_silence",
    "machine_end_other",
    "fax",
}


def _used_media_stream(profiling_run: ProfilingRun) -> bool:
    """Solo factura stream cuando el TwiML se ejecutó o ElevenLabs confirmó conversación."""
    return profiling_run.status in {
        ProfilingRunStatus.ANSWERED.value,
        ProfilingRunStatus.COMPLETED.value,
    } or bool(profiling_run.elevenlabs_conversation_id)


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


async def _mark_cached_call_answered(run_id: str, answered_by: str | None) -> None:
    """Persiste ANSWERED despues de enviar el TwiML cacheado a Twilio."""
    async with AsyncSessionFactory() as db:
        try:
            profiling_run = await _get_run_or_none(db, run_id)
            if not profiling_run:
                return
            if profiling_run.status in {
                ProfilingRunStatus.COMPLETED.value,
                ProfilingRunStatus.FAILED.value,
                ProfilingRunStatus.CANCELLED.value,
                ProfilingRunStatus.NO_ANSWER.value,
                ProfilingRunStatus.VOICEMAIL_DETECTED.value,
            }:
                return
            if answered_by:
                profiling_run.amd_result = str(answered_by)
            if profiling_run.status == ProfilingRunStatus.CALLING.value:
                pc = await db.get(ProcessCandidate, profiling_run.process_candidate_id)
                if pc:
                    await transition_profiling_async(
                        db, profiling_run, pc, ProfilingRunStatus.ANSWERED
                    )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("[twilio][twiml] fallo persistiendo respuesta cacheada run=%s", run_id)


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
    request: Request,
    run_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Webhook que Twilio invoca al conectar la llamada. Con AMD asíncrono no contiene
    aún ``AnsweredBy``: el TwiML precargado se devuelve de inmediato y el resultado
    llega después a ``/twilio/amd-status``.
    """
    form = await request.form()
    signature = request.headers.get("X-Twilio-Signature")
    url = _build_twilio_webhook_url(request)
    valid = await asyncio.to_thread(
        partial(twilio_client.validate_twilio_signature, url, _form_to_str_dict(form), signature)
    )
    if not valid:
        raise HTTPException(status_code=403, detail="Firma de Twilio invalida")

    answered_by_value = form.get("AnsweredBy")
    answered_by = answered_by_value if isinstance(answered_by_value, str) else None
    call_sid = str(form.get("CallSid", ""))
    to_number = str(form.get("To", ""))

    # Camino caliente: AMD ya confirmo que no es maquina y el worker preparo
    # el TwiML mientras el telefono timbraba. Responder sin esperar PostgreSQL.
    if answered_by not in _MACHINE_ANSWERED_BY:
        prepared_twiml = await get_prepared_twiml(run_id, call_sid)
        if prepared_twiml:
            background_tasks.add_task(_mark_cached_call_answered, run_id, answered_by)
            logger.info(
                "[twilio][twiml] cache hit run=%s sid=%s answered_by=%s",
                run_id,
                call_sid,
                answered_by,
            )
            return Response(content=prepared_twiml, media_type="application/xml")

    # El worker prepara el contexto antes de marcar. En el camino caliente solo
    # necesitamos el run y su ProcessCandidate para aplicar la transicion.
    cached_context = await get_call_context(run_id)
    if cached_context:
        profiling_run = await db.get(ProfilingRun, uuid.UUID(run_id))
        pc = (
            await db.execute(
                select(ProcessCandidate).where(
                    ProcessCandidate.id == profiling_run.process_candidate_id
                )
            )
        ).scalar_one_or_none() if profiling_run else None
        process = question_set = candidate = None
    else:
        # Compatibilidad para corridas antiguas que no alcanzaron a preparar cache.
        result = await db.execute(
            select(ProfilingRun)
            .where(ProfilingRun.id == uuid.UUID(run_id))
            .options(
                selectinload(ProfilingRun.question_set).selectinload(QuestionSet.questions),
                selectinload(ProfilingRun.process_candidate).selectinload(ProcessCandidate.candidate),
                selectinload(ProfilingRun.process_candidate).selectinload(ProcessCandidate.process),
            )
        )
        profiling_run = result.scalar_one_or_none()
        pc = profiling_run.process_candidate if profiling_run else None
        process = pc.process if pc else None
        question_set = profiling_run.question_set if profiling_run else None
        candidate = pc.candidate if pc else None
    if not profiling_run:
        logger.error(f"[twilio][twiml] ProfilingRun {run_id} no encontrado")
        return Response(content=_TWIML_HANGUP, media_type="application/xml")

    if profiling_run.status in {
        ProfilingRunStatus.FAILED.value,
        ProfilingRunStatus.CANCELLED.value,
        ProfilingRunStatus.COMPLETED.value,
        ProfilingRunStatus.NO_ANSWER.value,
        ProfilingRunStatus.VOICEMAIL_DETECTED.value,
    }:
        logger.warning(
            "[twilio][twiml] callback tardio ignorado para run terminal %s (%s)",
            run_id,
            profiling_run.status,
        )
        return Response(content=_TWIML_HANGUP, media_type="application/xml")

    if answered_by in _MACHINE_ANSWERED_BY:
        profiling_run.amd_result = str(answered_by or "machine")
        await db.commit()
        retry_or_fail_profiling_call.delay(str(profiling_run.id), f"AMD:{answered_by}")
        return Response(content=_TWIML_HANGUP, media_type="application/xml")

    # Humano: usar el contexto preparado o resolverlo solo como fallback.
    profiling_run.amd_result = str(answered_by)
    if not pc:
        logger.error(f"[twilio][twiml] datos incompletos para ProfilingRun {run_id}")
        await db.commit()
        return Response(content=_TWIML_HANGUP, media_type="application/xml")

    await transition_profiling_async(db, profiling_run, pc, ProfilingRunStatus.ANSWERED)
    if cached_context:
        voice_config = voice_config_from_context(cached_context)
        dynamic_variables = cached_context["dynamic_variables"]
        to_number = cached_context.get("to_number") or to_number
    else:
        from src.infrastructure.ai.prompts import VOICE_CALL_AGENT_BASE_PROMPT
        from src.infrastructure.cache.redis_client import get_active_ai_prompt

        universal_prompt = await get_active_ai_prompt(
            db, AITaskType.VOICE_CALL_AGENT.value, VOICE_CALL_AGENT_BASE_PROMPT
        )
        if not (process and question_set and candidate):
            logger.error(f"[twilio][twiml] datos incompletos para ProfilingRun {run_id}")
            await db.commit()
            return Response(content=_TWIML_HANGUP, media_type="application/xml")
        voice_config = resolve_voice_config(
            question_set, process, pc.whatsapp_consent_status, universal_prompt
        )
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
        await transition_profiling_async(
            db,
            profiling_run,
            pc,
            ProfilingRunStatus.FAILED,
            detail="elevenlabs_register_failed",
        )
        await db.commit()
        return Response(content=_TWIML_HANGUP, media_type="application/xml")

    await db.commit()
    return Response(content=twiml, media_type="application/xml")


@router.post("/twilio/amd-status")
async def twilio_async_amd_webhook(
    request: Request, run_id: str, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """Persiste el veredicto de AMD asíncrono y corta máquinas/fax."""
    form = await request.form()
    signature = request.headers.get("X-Twilio-Signature")
    url = _build_twilio_webhook_url(request)
    valid = await asyncio.to_thread(
        partial(twilio_client.validate_twilio_signature, url, _form_to_str_dict(form), signature)
    )
    if not valid:
        raise HTTPException(status_code=403, detail="Firma de Twilio invalida")

    call_sid = str(form.get("CallSid", ""))
    answered_by = str(form.get("AnsweredBy", "unknown"))
    duration_value = form.get("MachineDetectionDuration")
    duration_ms = int(duration_value) if isinstance(duration_value, str) else 0
    profiling_run = await _get_run_or_none(db, run_id)
    if not profiling_run or profiling_run.twilio_call_sid != call_sid:
        return {"status": "ignored"}

    profiling_run.amd_result = answered_by
    profiling_run.twilio_status_detail = f"amd:{answered_by}:{duration_ms}ms"
    await db.commit()

    if answered_by in _MACHINE_ANSWERED_BY:
        await asyncio.to_thread(twilio_client.end_call, call_sid)
        retry_or_fail_profiling_call.delay(str(profiling_run.id), f"AMD:{answered_by}")
        return {"status": "terminated"}
    return {"status": "ok"}


@router.post("/twilio/status")
async def twilio_status_webhook(
    request: Request, run_id: str, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    """
    Dos cosas distintas en el mismo webhook:
    1. Captura llamadas que nunca llegaron a /twiml (no-answer/busy/failed/canceled) —
       la unica forma de saber que una llamada jamas conecto, ya que AMD no llega a correr.
    2. Registra el costo de Twilio cuando la llamada termina. Usa el precio de
       conectividad del Call Resource y suma AMD/Media Stream según la tarifa pública.
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

    profiling_run = await _get_run_or_none(db, run_id)
    if not profiling_run:
        return {"status": "ignored"}

    if call_status == "completed" and profiling_run.twilio_call_sid == call_sid:
        duration_value = form.get("CallDuration") or form.get("Duration")
        form_duration_s = int(duration_value) if isinstance(duration_value, str) else 0
        try:
            billing = await asyncio.to_thread(twilio_client.fetch_call_billing, call_sid)
            duration_s = billing.duration_s or form_duration_s
            connectivity_cost = billing.connectivity_cost_usd
            currency = billing.currency
        except Exception:
            logger.exception("[twilio][cost] no se pudo consultar Call Resource sid=%s", call_sid)
            duration_s = form_duration_s
            connectivity_cost = None
            currency = "USD"
        if duration_s > 0:
            pc_result = await db.execute(
                select(ProcessCandidate).where(
                    ProcessCandidate.id == profiling_run.process_candidate_id
                )
            )
            pc = pc_result.scalar_one_or_none()
            process = await db.get(HiringProcess, pc.process_id) if pc else None
            amd_used = bool(profiling_run.amd_result)
            media_stream_used = _used_media_stream(profiling_run)
            cost = calculate_twilio_cost(
                duration_s,
                connectivity_cost,
                amd_used=amd_used,
                media_stream_used=media_stream_used,
            )
            await record_cost_async(
                db,
                process_id=pc.process_id if pc else None,
                candidate_id=pc.candidate_id if pc else None,
                user_id=process.recruiter_id if process else None,
                operation_type=OperationType.TWILIO_CALL.value,
                provider="TWILIO",
                model_used=(
                    "twilio-voice"
                    + ("+amd" if amd_used else "")
                    + ("+media-stream" if media_stream_used else "")
                ),
                call_duration_s=duration_s,
                estimated_cost=cost.amount_usd,
                currency=currency,
                cost_source=cost.source,
                external_reference=f"twilio:{call_sid}",
                cost_breakdown={
                    **cost.breakdown,
                    "amd_result": profiling_run.amd_result,
                },
            )
            await db.commit()
        return {"status": "ok"}

    if call_status not in _NO_CONNECT_CALL_STATUSES:
        return {"status": "ignored"}

    # Idempotencia: si /twiml ya proceso esta llamada (AMD corrio) o ya se reintento
    # con un CallSid nuevo, este evento de /status ya quedo obsoleto.
    if profiling_run.twilio_call_sid != call_sid:
        return {"status": "ignored"}
    if profiling_run.status != ProfilingRunStatus.CALLING.value:
        return {"status": "ignored"}

    profiling_run.twilio_status_detail = call_status
    await db.commit()
    retry_or_fail_profiling_call.delay(str(profiling_run.id), f"status:{call_status}")
    return {"status": "ok"}


_TRANSCRIPT_SPEAKER_LABEL = {"agent": "Agente", "user": "Candidato"}


def _format_transcript_text(turns: list[dict[str, Any]]) -> str:
    """Convierte el array de turnos de ElevenLabs (role/message) en texto legible
    para el prompt de evaluacion — antes se le pasaba la lista cruda al prompt."""
    lines = []
    for turn in turns:
        role = _TRANSCRIPT_SPEAKER_LABEL.get(turn.get("role"), turn.get("role") or "?")
        message = turn.get("message") or ""
        if message:
            lines.append(f"{role}: {message}")
    return "\n".join(lines)


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

    if not twilio_call_sid:
        metadata = data.get("metadata", {}) or {}
        phone_call = metadata.get("phone_call", {}) or {}
        twilio_call_sid = phone_call.get("call_sid") or metadata.get("call_sid")

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
        await asyncio.to_thread(delete_call_context_sync, str(profiling_run.id))
        return {"status": "ok", "idempotent": True}
    if profiling_run.status in {
        ProfilingRunStatus.FAILED.value,
        ProfilingRunStatus.CANCELLED.value,
        ProfilingRunStatus.NO_ANSWER.value,
        ProfilingRunStatus.VOICEMAIL_DETECTED.value,
    }:
        logger.warning(
            "[elevenlabs][post-call] callback tardio ignorado para run terminal %s (%s)",
            profiling_run.id,
            profiling_run.status,
        )
        return {"status": "ignored", "reason": "run_terminal"}

    if profiling_run.amd_result in _MACHINE_ANSWERED_BY:
        logger.warning(
            "[elevenlabs][post-call] conversación de máquina ignorada run=%s amd=%s",
            profiling_run.id,
            profiling_run.amd_result,
        )
        return {"status": "ignored", "reason": "amd_machine"}

    analysis = data.get("analysis", {}) or {}
    metadata = data.get("metadata", {}) or {}
    raw_transcript = (
        data.get("transcript") or data.get("conversation_transcript") or data.get("turns") or []
    )

    formatted_turns = []
    for t in raw_transcript:
        if isinstance(t, dict):
            msg = (t.get("message") or t.get("text") or "").strip()
            if msg:
                formatted_turns.append(
                    {
                        "role": t.get("role", "user"),
                        "message": msg,
                        "time_in_call_secs": t.get("time_in_call_secs") or t.get("time_in_call"),
                    }
                )
        elif hasattr(t, "role"):
            msg = (getattr(t, "message", "") or "").strip()
            if msg:
                formatted_turns.append(
                    {
                        "role": getattr(t, "role", "user"),
                        "message": msg,
                        "time_in_call_secs": getattr(t, "time_in_call_secs", None),
                    }
                )

    transcript_text = _format_transcript_text(formatted_turns)

    profiling_run.elevenlabs_conversation_id = conversation_id
    profiling_run.transcript_summary = analysis.get("transcript_summary")
    profiling_run.transcript_turns = formatted_turns
    pc = await db.get(ProcessCandidate, profiling_run.process_candidate_id)
    if pc:
        try:
            await transition_profiling_async(
                db,
                profiling_run,
                pc,
                ProfilingRunStatus.COMPLETED,
            )
        except BusinessRuleException as exc:
            logger.warning(f"[elevenlabs][post-call] transicion invalida para {pc.id}: {exc}")

    voice_cost = calculate_elevenlabs_cost(metadata)
    input_tokens, output_tokens, cached_tokens, llm_models = extract_elevenlabs_llm_usage(
        metadata
    )
    process = await db.get(HiringProcess, pc.process_id) if pc else None
    await record_cost_async(
        db,
        process_id=pc.process_id if pc else None,
        candidate_id=pc.candidate_id if pc else None,
        user_id=process.recruiter_id if process else None,
        operation_type=OperationType.VOICE_CALL.value,
        provider="ELEVENLABS",
        model_used=(
            "elevenlabs-conversational-ai"
            + (f":{','.join(llm_models)}" if llm_models else "")
        ),
        tokens_input=input_tokens,
        tokens_cached=cached_tokens,
        tokens_output=output_tokens,
        call_duration_s=int(metadata.get("call_duration_secs", 0) or 0),
        estimated_cost=voice_cost.amount_usd,
        cost_source=voice_cost.source,
        external_reference=f"elevenlabs:{conversation_id}",
        cost_breakdown=voice_cost.breakdown,
    )

    await db.commit()

    # El contexto solo es necesario hasta que llega el post-call.
    await asyncio.to_thread(delete_call_context_sync, str(profiling_run.id))

    evaluate_profiling_transcription.delay(str(profiling_run.id), transcript_text)
    return {"status": "ok"}
