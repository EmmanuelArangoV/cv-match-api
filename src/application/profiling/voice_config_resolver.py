"""
Resuelve la configuracion de voz (ElevenLabs) efectiva para una llamada de profiling.

Precedencia técnica: HiringProcess.voice_override_* (si no es None) > QuestionSet.default_*
(si no es None) > settings.elevenlabs_agent_id. El prompt y el saludo llegan obligatoriamente
desde una misma revisión propia del proceso.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config import settings
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import (
    HiringProcess,
    ProfilingQuestion,
    QuestionSet,
    QuestionType,
)


@dataclass(frozen=True)
class VoiceCallConfig:
    agent_id: str
    system_prompt: str | None
    first_message: str
    language: str | None
    llm_model: str | None
    voice_id: str | None
    tts_stability: float | None
    tts_speed: float | None
    tts_similarity_boost: float | None


def _pick[T](override: T | None, default: T | None) -> T | None:
    return override if override is not None else default


_GUIDED_ANSWER_TYPES = {
    QuestionType.CLOSED,
    QuestionType.MULTIPLE_CHOICE,
    QuestionType.YES_NO,
    QuestionType.NUMERIC,
}


def _build_questions_block(questions: list[ProfilingQuestion]) -> str:
    """Agrupa el cuestionario en bloques conversacionales, sin exponer tipos técnicos."""
    ordered = sorted(questions, key=lambda q: q.order_index)
    guided_questions: list[ProfilingQuestion] = []
    exploratory_questions: list[ProfilingQuestion] = []
    for question in ordered:
        try:
            question_type = QuestionType(question.type)
        except ValueError:
            question_type = QuestionType.OPEN
        if question_type in _GUIDED_ANSWER_TYPES:
            guided_questions.append(question)
        else:
            exploratory_questions.append(question)

    sections = [
        "Cuestionario de profiling. Mantén una conversación fluida: formula una pregunta a la "
        "vez, escucha la respuesta completa y no leas etiquetas técnicas ni expliques la "
        "mecánica antes de cada pregunta.",
    ]
    if guided_questions:
        sections.extend(
            [
                "Información práctica y disponibilidad:\n"
                "Introduce este bloque una sola vez, con naturalidad: \"Ahora quiero conocer "
                "algunos aspectos prácticos de tu disponibilidad. Puedes responder con la opción "
                "o el dato concreto que mejor refleje tu situación; por ejemplo, sí o no cuando "
                "aplique.\"",
                *(
                    f"{index}. {question.text}"
                    for index, question in enumerate(guided_questions, start=1)
                ),
            ]
        )
    if exploratory_questions:
        sections.extend(
            [
                "Experiencia o situación actual:\n"
                "Introduce este bloque una sola vez, con naturalidad: \"Para estas preguntas, "
                "cuéntame con base en tu experiencia o situación actual.\"",
                *(
                    f"{index}. {question.text}"
                    for index, question in enumerate(exploratory_questions, start=1)
                ),
            ]
        )
    return "\n\n".join(sections)


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
    process_first_message: str | None = None,
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
    first_message = (process_first_message or "").strip()
    if not process_prompt or not process_prompt.strip():
        raise BusinessRuleException("El proceso no tiene instrucciones activas para la llamada.")
    if not first_message:
        raise BusinessRuleException("El proceso no tiene un saludo inicial activo para la llamada.")

    return VoiceCallConfig(
        agent_id=_pick(process.voice_override_agent_id, question_set.default_agent_id)
        or settings.elevenlabs_agent_id,
        system_prompt=system_prompt,
        first_message=first_message,
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
