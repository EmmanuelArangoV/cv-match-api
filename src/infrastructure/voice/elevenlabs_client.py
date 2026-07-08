"""
Cliente de ElevenLabs para registrar llamadas de Twilio y verificar firmas de webhooks.

`register_call` es el patron BYO-Twilio del SDK oficial: dado un CallSid ya creado
en Twilio (con AMD sincrono confirmando que contesto un humano), le pide a ElevenLabs
que arme y devuelva el TwiML que conecta la llamada al agente conversacional, con el
system prompt/voz/idioma inyectados dinamicamente via `conversation_config_override`.
"""
import logging
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
    agent_override = AgentConfigOverrideInput(
        first_message=voice_config.first_message,
        language=voice_config.language,
        prompt=PromptAgentApiModelOverrideInput(
            prompt=voice_config.system_prompt,
            llm=voice_config.llm_model,
        )
        if voice_config.system_prompt or voice_config.llm_model
        else None,
    )
    tts_override = TtsConversationalConfigOverride(
        voice_id=voice_config.voice_id,
        stability=voice_config.tts_stability,
        speed=voice_config.tts_speed,
        similarity_boost=voice_config.tts_similarity_boost,
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
