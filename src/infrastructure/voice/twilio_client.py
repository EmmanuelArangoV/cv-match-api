"""
Cliente de Twilio para llamadas salientes de profiling.

Dispara la llamada directamente contra la API REST de Twilio con AMD sincrono
(MachineDetection=Enable): asi ElevenLabs solo entra a la linea cuando Twilio ya
confirmo que contesto un humano, y los buzones de voz no generan costo de agente.
Patron tomado del proyecto de referencia RiwiCalls/SofIA (twilio/client.js).
"""

import logging

from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioRestClient

from src.config import settings

logger = logging.getLogger(__name__)

_client: TwilioRestClient | None = None


def _get_client() -> TwilioRestClient:
    global _client
    if _client is None:
        _client = TwilioRestClient(settings.twilio_account_sid, settings.twilio_auth_token)
    return _client


def create_outbound_call(to_phone: str, run_id: str) -> str:
    """Dispara la llamada saliente con AMD sincrono. Retorna el CallSid de Twilio."""
    base_url = settings.public_base_url.rstrip("/")
    call = _get_client().calls.create(
        to=to_phone,
        from_=settings.twilio_from_number,
        url=f"{base_url}/api/v1/webhooks/twilio/twiml?run_id={run_id}",
        status_callback=f"{base_url}/api/v1/webhooks/twilio/status?run_id={run_id}",
        status_callback_event=["completed"],
        machine_detection="Enable",
        machine_detection_timeout=settings.machine_detection_timeout,
        timeout=settings.twilio_ring_timeout_seconds,
    )
    logger.info(f"[twilio] llamada saliente creada sid={call.sid} run_id={run_id}")
    return str(call.sid)


def validate_twilio_signature(url: str, params: dict[str, str], signature: str | None) -> bool:
    """Verifica X-Twilio-Signature. Si twilio_validate_signature=False, siempre valida."""
    if not settings.twilio_validate_signature:
        return True
    if not signature:
        return False
    validator = RequestValidator(settings.twilio_auth_token)
    return bool(validator.validate(url, params, signature))
