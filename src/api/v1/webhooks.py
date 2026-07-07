import hashlib
import hmac

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from src.infrastructure.db.models import ProfilingRun, ProfilingRunStatus, ProcessCandidate, CandidateStatus

logger = logging.getLogger(__name__)

from src.application.candidate.whatsapp_message_usecase import ProcessWhatsAppMessageUseCase
from src.config import settings
from src.infrastructure.db.database import get_db

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


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


@router.post("/twilio/amd")
async def twilio_amd_webhook(
    request: Request,
    run_id: str,
    AnsweredBy: str = Form(None),
    CallSid: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook que Twilio llama tras realizar Answering Machine Detection.
    Parámetros form-data: 
    - AnsweredBy: machine_start, machine_end_beep, machine_end_silence, machine_end_other, human, unknown
    - CallSid
    """
    logger.info(f"[TWILIO WEBHOOK] RunID: {run_id} | AnsweredBy: {AnsweredBy} | CallSid: {CallSid}")
    
    import uuid
    try:
        run_uuid = uuid.UUID(run_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid run_id")
        
    profiling_run = await db.get(ProfilingRun, run_uuid)
    
    if not profiling_run:
        logger.error(f"ProfilingRun {run_id} not found")
        return {"error": "not found"}

    pc = await db.get(ProcessCandidate, profiling_run.process_candidate_id)

    # Si fue contestador automático o desconocido
    if AnsweredBy in ("machine_start", "machine_end_beep", "machine_end_silence", "machine_end_other", "unknown", None):
        profiling_run.status = ProfilingRunStatus.NO_ANSWER.value
        if pc:
            pc.status = CandidateStatus.PROFILING_FAILED.value
        await db.commit()
        # Twilio necesita TwiML para colgar
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'
        return Response(content=twiml, media_type="application/xml")

    # Si fue humano
    profiling_run.status = ProfilingRunStatus.ANSWERED.value
    await db.commit()
    
    # Twilio necesita TwiML para conectar la llamada al stream de ElevenLabs
    from src.config import settings
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://api.elevenlabs.io/v1/convai/conversation?agent_id={getattr(settings, 'elevenlabs_agent_id', 'mock')}">
            <Parameter name="profiling_run_id" value="{run_id}" />
        </Stream>
    </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/elevenlabs")
async def elevenlabs_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook que ElevenLabs llama al finalizar la conversación (post-call transcript).
    """
    payload = await request.json()
    logger.info(f"[ELEVENLABS WEBHOOK] Recibido payload")
    
    # Extraer custom_variables (que enviamos en el Stream Parameter) para encontrar el run_id
    custom_vars = payload.get("custom_variables", {})
    run_id = custom_vars.get("profiling_run_id")
    
    if not run_id:
        # Intento fallback
        run_id = payload.get("conversation_id")
        logger.warning(f"No run_id en custom_variables, usando id {run_id}")
        return {"status": "ignored"}

    import uuid
    try:
        run_uuid = uuid.UUID(run_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid run_id")
        
    profiling_run = await db.get(ProfilingRun, run_uuid)
    
    if not profiling_run:
        logger.error(f"ProfilingRun {run_id} no encontrado en webhook elevenlabs")
        return {"error": "not found"}

    # Extraer transcripción
    transcript = payload.get("transcript", "")
    profiling_run.transcription_url = "webhook_payload" # simulado
    profiling_run.status = ProfilingRunStatus.COMPLETED.value
    
    await db.commit()
    
    # Encolar la evaluación post-profiling con la transcripción
    from src.infrastructure.workers.tasks.profiling import evaluate_profiling_transcription
    evaluate_profiling_transcription.delay(str(run_id), transcript)
    
    return {"status": "ok"}

