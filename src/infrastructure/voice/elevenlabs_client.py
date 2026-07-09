"""
Cliente de ElevenLabs para registrar llamadas de Twilio y verificar firmas de webhooks.

`register_call` es el patron BYO-Twilio del SDK oficial: dado un CallSid ya creado
en Twilio (con AMD sincrono confirmando que contesto un humano), le pide a ElevenLabs
que arme y devuelva el TwiML que conecta la llamada al agente conversacional, con el
system prompt/voz/idioma inyectados dinamicamente via `conversation_config_override`.
"""

import logging
import time
from typing import Any

from elevenlabs.client import ElevenLabs
from elevenlabs.types import (
    AgentConfigOverrideInput,
    ConversationConfigClientOverrideInput,
    ConversationInitiationClientDataRequestInput,
    PromptAgentApiModelOverrideInput,
    TtsConversationalConfigOverride,
)

from src.application.profiling.voice_config_resolver import VoiceCallConfig
from src.config import settings

logger = logging.getLogger(__name__)

_client: ElevenLabs | None = None

# Cache de que campos de conversation_config_override tiene habilitados cada agente
# (pestaña "Seguridad" del dashboard). Enviar un override que el agente no permite no
# lo ignora en silencio: ElevenLabs cierra el websocket (code 1008) y la conversacion
# entera muere sin audio — de ahi que valga la pena cachear esto (TTL corto) en vez de
# confiar en que la config nunca cambia, pero sin pagar una consulta extra por llamada.
_ALLOWED_OVERRIDES_TTL_SECONDS = 300
_allowed_overrides_cache: dict[str, tuple[float, dict[str, bool]]] = {}


def _get_allowed_overrides(agent_id: str) -> dict[str, bool]:
    now = time.monotonic()
    cached = _allowed_overrides_cache.get(agent_id)
    if cached and now - cached[0] < _ALLOWED_OVERRIDES_TTL_SECONDS:
        return cached[1]

    allowed = {
        "first_message": False,
        "language": False,
        "prompt": False,
        "llm": False,
        "voice_id": False,
        "stability": False,
        "speed": False,
        "similarity_boost": False,
    }
    try:
        agent = get_elevenlabs_client().conversational_ai.agents.get(agent_id=agent_id)
        ov = (
            agent.platform_settings.overrides.conversation_config_override
            if agent.platform_settings and agent.platform_settings.overrides
            else None
        )
        if ov:
            if ov.agent:
                allowed["first_message"] = bool(ov.agent.first_message)
                allowed["language"] = bool(ov.agent.language)
                if ov.agent.prompt:
                    allowed["prompt"] = bool(ov.agent.prompt.prompt)
                    allowed["llm"] = bool(ov.agent.prompt.llm)
            if ov.tts:
                allowed["voice_id"] = bool(ov.tts.voice_id)
                allowed["stability"] = bool(ov.tts.stability)
                allowed["speed"] = bool(ov.tts.speed)
                allowed["similarity_boost"] = bool(ov.tts.similarity_boost)
    except Exception as exc:
        # Fail-closed: si no podemos confirmar que un override esta permitido, no lo
        # mandamos — es preferible una llamada con la config por defecto del agente
        # a una que ElevenLabs rechaza de plano.
        logger.error(f"[elevenlabs] no se pudo leer overrides permitidos de {agent_id}: {exc}")

    _allowed_overrides_cache[agent_id] = (now, allowed)
    return allowed


def get_elevenlabs_client() -> ElevenLabs:
    global _client
    if _client is None:
        options: dict[str, Any] = {"api_key": settings.elevenlabs_api_key}
        if settings.elevenlabs_base_url:
            options["base_url"] = settings.elevenlabs_base_url
        _client = ElevenLabs(**options)
    return _client


def _build_conversation_config_override(
    voice_config: VoiceCallConfig,
) -> ConversationConfigClientOverrideInput:
    allowed = _get_allowed_overrides(voice_config.agent_id)
    skipped = [
        field
        for field, value in (
            ("first_message", voice_config.first_message),
            ("language", voice_config.language),
            ("prompt", voice_config.system_prompt),
            ("llm", voice_config.llm_model),
            ("voice_id", voice_config.voice_id),
            ("stability", voice_config.tts_stability),
            ("speed", voice_config.tts_speed),
            ("similarity_boost", voice_config.tts_similarity_boost),
        )
        if value is not None and not allowed[field]
    ]
    if skipped:
        logger.warning(
            f"[elevenlabs] agente {voice_config.agent_id} no permite overrides de "
            f"{skipped} (deshabilitados en su config de seguridad) — se omiten para "
            "no romper la conexion."
        )

    prompt_override = (
        PromptAgentApiModelOverrideInput(
            prompt=voice_config.system_prompt if allowed["prompt"] else None,
            llm=voice_config.llm_model if allowed["llm"] else None,
        )
        if (voice_config.system_prompt and allowed["prompt"])
        or (voice_config.llm_model and allowed["llm"])
        else None
    )
    agent_override = AgentConfigOverrideInput(
        first_message=voice_config.first_message if allowed["first_message"] else None,
        language=voice_config.language if allowed["language"] else None,
        prompt=prompt_override,
    )
    tts_override = TtsConversationalConfigOverride(
        voice_id=voice_config.voice_id if allowed["voice_id"] else None,
        stability=voice_config.tts_stability if allowed["stability"] else None,
        speed=voice_config.tts_speed if allowed["speed"] else None,
        similarity_boost=voice_config.tts_similarity_boost if allowed["similarity_boost"] else None,
    )
    return ConversationConfigClientOverrideInput(agent=agent_override, tts=tts_override)


def register_call(
    voice_config: VoiceCallConfig,
    dynamic_variables: dict[str, str],
    to_number: str,
    call_sid: str,
) -> str:
    """Registra la llamada de Twilio en ElevenLabs y retorna el TwiML a responder."""
    client_data = ConversationInitiationClientDataRequestInput(
        conversation_config_override=_build_conversation_config_override(voice_config),
        dynamic_variables={**dynamic_variables, "twilio_call_sid": call_sid},
    )
    twiml = get_elevenlabs_client().conversational_ai.twilio.register_call(
        agent_id=voice_config.agent_id,
        from_number=settings.twilio_from_number,
        to_number=to_number,
        direction="outbound",
        conversation_initiation_client_data=client_data,
    )
    logger.info(f"[elevenlabs] register_call OK agent_id={voice_config.agent_id} sid={call_sid}")
    return str(twiml)


def verify_webhook_signature(raw_body: str, sig_header: str | None) -> dict[str, Any]:
    """Verifica la firma del webhook post_call_transcription. Lanza BadRequestError si falla."""
    event: dict[str, Any] = get_elevenlabs_client().webhooks.construct_event(
        raw_body, sig_header or "", settings.elevenlabs_webhook_secret_transcription
    )
    return event
