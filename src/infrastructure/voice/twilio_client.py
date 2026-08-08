"""
Cliente de Twilio para llamadas salientes de profiling.

Dispara la llamada directamente contra la API REST de Twilio. AMD puede ejecutarse
en segundo plano para que Twilio entregue el TwiML sin bloquear el primer audio.
Patron tomado del proyecto de referencia RiwiCalls/SofIA (twilio/client.js).
"""

import logging
from dataclasses import dataclass

from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioRestClient

from src.config import settings

logger = logging.getLogger(__name__)

_client: TwilioRestClient | None = None


@dataclass(frozen=True)
class TwilioCallBilling:
    duration_s: int
    connectivity_cost_usd: str | None
    currency: str
    answered_by: str | None


def _get_client() -> TwilioRestClient:
    global _client
    if _client is None:
        _client = TwilioRestClient(settings.twilio_account_sid, settings.twilio_auth_token)
    return _client


def create_outbound_call(to_phone: str, run_id: str) -> str:
    """Dispara una llamada saliente y retorna el CallSid de Twilio."""
    base_url = settings.public_base_url.rstrip("/")
    call_params = {
        "to": to_phone,
        "from_": settings.twilio_from_number,
        "url": f"{base_url}/api/v1/webhooks/twilio/twiml?run_id={run_id}",
        "status_callback": f"{base_url}/api/v1/webhooks/twilio/status?run_id={run_id}",
        "status_callback_event": ["completed"],
        "timeout": settings.twilio_ring_timeout_seconds,
    }
    if settings.twilio_machine_detection_enabled:
        call_params.update(
            machine_detection="Enable",
            machine_detection_timeout=settings.machine_detection_timeout,
        )
        if settings.twilio_machine_detection_async:
            call_params.update(
                async_amd=True,
                async_amd_status_callback=(
                    f"{base_url}/api/v1/webhooks/twilio/amd-status?run_id={run_id}"
                ),
                async_amd_status_callback_method="POST",
            )

    call = _get_client().calls.create(**call_params)
    logger.info(f"[twilio] llamada saliente creada sid={call.sid} run_id={run_id}")
    return str(call.sid)


def fetch_call_billing(call_sid: str) -> TwilioCallBilling:
    """Obtiene el precio de conectividad que Twilio publicó para el CallSid."""
    call = _get_client().calls(call_sid).fetch()
    return TwilioCallBilling(
        duration_s=int(call.duration or 0),
        connectivity_cost_usd=str(call.price) if call.price is not None else None,
        currency=str(call.price_unit or "USD"),
        answered_by=str(call.answered_by) if call.answered_by else None,
    )


def end_call(call_sid: str) -> None:
    """Finaliza una llamada activa tras detectar máquina/fax con AMD asíncrono."""
    _get_client().calls(call_sid).update(status="completed")


def validate_twilio_signature(url: str, params: dict[str, str], signature: str | None) -> bool:
    """Verifica X-Twilio-Signature. Si twilio_validate_signature=False, siempre valida."""
    if not settings.twilio_validate_signature:
        return True
    if not signature:
        return False
    validator = RequestValidator(settings.twilio_auth_token)
    return bool(validator.validate(url, params, signature))
