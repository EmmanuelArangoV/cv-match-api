"""
Resuelve la configuracion de voz (ElevenLabs) efectiva para una llamada de profiling.

Precedencia: HiringProcess.voice_override_* (si no es None) > QuestionSet.default_* (si no
es None) > settings.elevenlabs_agent_id como unico fallback (el resto queda en None para que
ElevenLabs use lo configurado en el dashboard del agente).
"""
from __future__ import annotations

from dataclasses import dataclass

from src.config import settings
from src.infrastructure.db.models import HiringProcess, QuestionSet


@dataclass(frozen=True)
class VoiceCallConfig:
    agent_id: str
    system_prompt: str | None
    first_message: str | None
    language: str | None
    llm_model: str | None
    voice_id: str | None
    tts_stability: float | None
    tts_speed: float | None
    tts_similarity_boost: float | None


def _pick(override: object | None, default: object | None) -> object | None:
    return override if override is not None else default


def resolve_voice_config(question_set: QuestionSet, process: HiringProcess) -> VoiceCallConfig:
    return VoiceCallConfig(
        agent_id=_pick(process.voice_override_agent_id, question_set.default_agent_id)
        or settings.elevenlabs_agent_id,
        system_prompt=_pick(
            process.voice_override_system_prompt, question_set.default_system_prompt
        ),
        first_message=_pick(
            process.voice_override_first_message, question_set.default_first_message
        ),
        language=_pick(process.voice_override_language, question_set.default_language),
        llm_model=_pick(process.voice_override_llm_model, question_set.default_llm_model),
        voice_id=_pick(process.voice_override_voice_id, question_set.default_voice_id),
        tts_stability=_pick(
            process.voice_override_tts_stability, question_set.default_tts_stability
        ),
        tts_speed=_pick(process.voice_override_tts_speed, question_set.default_tts_speed),
        tts_similarity_boost=_pick(
            process.voice_override_tts_similarity_boost, question_set.default_tts_similarity_boost
        ),
    )
