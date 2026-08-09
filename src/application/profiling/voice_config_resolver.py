"""
Resuelve la configuracion de voz (ElevenLabs) efectiva para una llamada de profiling.

Precedencia técnica: HiringProcess.voice_override_* (si no es None) > QuestionSet.default_*
(si no es None) > settings.elevenlabs_agent_id. El prompt y el saludo llegan como una misma
revisión propia del proceso; la columna histórica del saludo solo queda como fallback de rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from src.config import settings
from src.infrastructure.db.models import HiringProcess, ProfilingQuestion, QuestionSet, QuestionType


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


_FIRST_MESSAGE_NOT_VERSIONED = object()


_QUESTION_TYPE_HINTS: dict[QuestionType, str] = {
    QuestionType.OPEN: "pregunta abierta",
    QuestionType.CLOSED: "pregunta cerrada",
    QuestionType.MULTIPLE_CHOICE: "pregunta de opción múltiple",
    QuestionType.YES_NO: "pregunta de sí o no",
    QuestionType.NUMERIC: "pregunta numérica",
}


def _build_questions_block(questions: list[ProfilingQuestion]) -> str:
    """
    Lista las preguntas del set con su tipo (OPEN/CLOSED/YES_NO/...) e instruye al agente
    a anunciar el tipo en lenguaje natural antes de formular cada una — p. ej. "la siguiente
    pregunta es de sí o no: ¿tienes experiencia con metodologías ágiles?".
    """
    ordered = sorted(questions, key=lambda q: q.order_index)
    lines = [
        f"{i}. [{_QUESTION_TYPE_HINTS.get(QuestionType(q.type), 'pregunta abierta')}] {q.text}"
        for i, q in enumerate(ordered, start=1)
    ]
    return (
        "Preguntas del cuestionario de profiling, en este orden. Antes de formular cada "
        "pregunta, anuncia brevemente en lenguaje natural qué tipo de pregunta es (por "
        'ejemplo: "la siguiente pregunta es de sí o no", "esta es una pregunta abierta", '
        '"esta pregunta tiene varias opciones para elegir") y luego hazla:\n' + "\n".join(lines)
    )


def _build_consent_note(whatsapp_consent_status: str | None) -> str:
    """
    Instruye al agente sobre si ya tiene consentimiento explicito (aceptado por WhatsApp
    antes de la llamada) o si debe pedirlo el mismo verbalmente al no haberlo obtenido
    a tiempo por ese canal.
    """
    if whatsapp_consent_status == "ACCEPTED":
        return (
            "El candidato ya dio su consentimiento explícito por WhatsApp para recibir esta "
            "llamada y para que sea grabada — NO le vuelvas a pedir permiso de grabación ni "
            "le leas términos y condiciones, ve directo al saludo breve y las preguntas."
        )
    return (
        "El candidato NO ha confirmado su consentimiento por WhatsApp (no respondió a tiempo "
        "o no se le pudo contactar por ese canal). Antes de continuar, pide su consentimiento "
        "explícito para grabar la llamada y continuar con la entrevista; si no acepta, "
        "agradece amablemente y termina la llamada sin insistir."
    )


def resolve_voice_config(
    question_set: QuestionSet,
    process: HiringProcess,
    whatsapp_consent_status: str | None = None,
    process_prompt: str | None = None,
    process_first_message: object = _FIRST_MESSAGE_NOT_VERSIONED,
) -> VoiceCallConfig:
    questions_block = (
        _build_questions_block(question_set.questions) if question_set.questions else None
    )
    # ``None`` significa que el caller no tiene contexto de consentimiento. En
    # ese caso conservamos el prompt configurado; los estados reales del flujo
    # (PENDING/TIMEOUT/ACCEPTED) sí agregan la instrucción correspondiente.
    consent_note = (
        _build_consent_note(whatsapp_consent_status)
        if whatsapp_consent_status is not None
        else None
    )
    system_prompt = "\n\n".join(p for p in (process_prompt, consent_note, questions_block) if p)
    # Un caller antiguo que omite el argumento conserva la columna legacy para rollback. Cuando
    # el caller trae una revision (incluso con NULL), esa revision manda: NULL significa usar el
    # saludo del set, no resucitar un override oculto que el usuario ya quitó de la interfaz.
    first_message = (
        _pick(process.voice_override_first_message, question_set.default_first_message)
        if process_first_message is _FIRST_MESSAGE_NOT_VERSIONED
        else _pick(process_first_message, question_set.default_first_message)
    )

    return VoiceCallConfig(
        agent_id=_pick(process.voice_override_agent_id, question_set.default_agent_id)
        or settings.elevenlabs_agent_id,
        system_prompt=system_prompt,
        first_message=cast(str | None, first_message),
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
