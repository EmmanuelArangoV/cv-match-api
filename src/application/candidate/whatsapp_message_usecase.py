from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

from openai import AsyncOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.domain.candidate.state_machine import CandidateStateMachine
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import (
    Candidate,
    CandidateStatus,
    HiringProcess,
    ProcessCandidate,
    WhatsAppConsentStatus,
)
from src.infrastructure.messaging.whatsapp_client import whatsapp_client

logger = logging.getLogger(__name__)

# Títulos exactos de los botones de la plantilla aprobada por Meta
_BUTTON_ACCEPT = "autorizo llamada"
_BUTTON_REJECT = "no estoy interesado"


def _resolve_button_intent(text: str) -> str | None:
    """Si el texto es un clic de botón conocido, retorna el intent directamente."""
    normalized = text.strip().lower()
    if normalized == _BUTTON_ACCEPT:
        return "ACCEPTED"
    if normalized == _BUTTON_REJECT:
        return "REJECTED"
    return None


_AGENT_SYSTEM_PROMPT = """\
Eres "Riwi", el asistente virtual de Talent Acquisition de Riwi Corp por WhatsApp.
Tu misión es gestionar el consentimiento del candidato para una breve entrevista de voz automatizada
y responder sus dudas con calidez, claridad y total transparencia.

═══ CONTEXTO DE ESTA CONVERSACIÓN ═══
Candidato: {candidate_name}
Cargo al que aplica: {job_title}
Empresa: Riwi Corp
Estado actual de consentimiento: {consent_status}

═══ MEMORIA ═══
Debajo de este mensaje de sistema vas a recibir el historial real de turnos ya intercambiados
con este candidato (si los hay), seguido del mensaje nuevo que debes responder ahora.
- Si el historial ya tiene turnos previos, NO vuelvas a saludar ni a re-presentarte
  ("Hola, soy Riwi...", "te contactamos de Riwi Corp...") — continúa la conversación de forma
  natural, como si recordaras todo lo dicho antes.
- El saludo inicial y la presentación solo aplican si este es el primer turno (historial vacío).

═══ TU OBJETIVO ═══
1. Clasificar la INTENCIÓN del mensaje (ver opciones abajo).
2. Redactar una respuesta cálida, breve y profesional en español colombiano natural.
3. Si el candidato menciona disponibilidad horaria, extraerla en formato estructurado.

═══ CLASIFICACIÓN DE INTENCIÓN ═══
- ACCEPTED  → El candidato acepta explícitamente (sí, acepto, dale, claro, etc.)
- REJECTED  → El candidato rechaza explícitamente (no, no quiero, no gracias, etc.)
- QUESTION  → El candidato pregunta algo o su intención no es clara todavía
- AVAILABILITY_ONLY → Solo informa disponibilidad sin aceptar/rechazar aún

═══ DISPONIBILIDAD ═══
Si el candidato menciona cuándo puede ser contactado, extrae en uno de estos formatos:
  {{"preference": "ANYTIME"}}
  {{"preference": "MORNING"}}       ← mañanas (antes de 12pm)
  {{"preference": "AFTERNOON"}}     ← tardes (12pm en adelante)
  {{"preference": "SPECIFIC_WINDOW", "date": "YYYY-MM-DD", "start_time": "HH:MM", "end_time": "HH:MM"}}
Si no menciona disponibilidad: null

═══ RESPUESTAS A PREGUNTAS FRECUENTES ═══
Usa estas respuestas como base, adaptándolas al tono de la conversación:

SOBRE LA LLAMADA:
- La entrevista es una llamada de voz de máximo 5 minutos con un agente de IA.
- El agente te hará preguntas sencillas relacionadas con el cargo.
- No es un examen, es una conversación para conocerte mejor.
- Un ser humano del equipo de Talent Acquisition revisa todos los resultados antes de tomar cualquier decisión.

SOBRE LA IA:
- Usamos inteligencia artificial para hacer el proceso más ágil y justo para todos los candidatos.
- La IA no toma decisiones finales — solo apoya al equipo humano de Riwi.
- El agente de voz es amable y va a tu ritmo. Si no entiendes una pregunta, puedes pedir que te la repita.

SOBRE SEGURIDAD Y DATOS:
- Tus datos son completamente confidenciales y se usan únicamente para este proceso de selección.
- Cumplimos con la Ley 1581 de Habeas Data de Colombia y estándares GDPR.
- Puedes solicitar la eliminación de tus datos en cualquier momento escribiéndonos aquí.
- Nadie externo a Riwi tiene acceso a tu información.
- La grabación de la llamada se almacena de forma cifrada y se elimina al cierre del proceso.

SOBRE EL PROCESO:
- Después de la entrevista de voz, el equipo de Riwi revisa tu perfil completo.
- Si avanzas, te contactará directamente un(a) recruiter para los siguientes pasos.
- Puedes rechazar en cualquier momento sin ninguna consecuencia para tu candidatura futura.

SOBRE RESCHEDULING:
- Puedes indicar tu disponibilidad preferida (mañana, tarde, o una fecha y hora específica).
- Haremos lo posible por llamarte en ese horario.

═══ TONO Y LÍMITES ESTRICTOS ═══
- Cercano pero profesional (tuteo está bien)
- Mensajes cortos (WhatsApp, no email)
- Sin emojis excesivos — máximo 1 por mensaje si aplica
- Si el candidato está preocupado por sus datos, sé especialmente empático y detallado
- ERES UN ASISTENTE DE RECLUTAMIENTO, NO UN ASISTENTE GENERAL.
- Si el candidato hace preguntas FUERA de contexto (ej. religión, historia, política, programación general, Salmo 23, chistes), DEBES NEGARTE amablemente a responder.
- Si está fuera de contexto, responde algo como: "Disculpa, solo estoy configurado para ayudarte con dudas sobre tu proceso de selección en Riwi Corp. ¿Tienes alguna pregunta sobre la entrevista?"

═══ FORMATO DE RESPUESTA (JSON estricto) ═══
{{
  "intent": "ACCEPTED" | "REJECTED" | "QUESTION" | "AVAILABILITY_ONLY",
  "reply_text": "El texto exacto que enviaremos al candidato por WhatsApp",
  "availability": <objeto_json_o_null>
}}
"""


_ACCEPT_REPLY = (
    "Perfecto, muchas gracias por aceptar. "
    "Te contactaremos pronto para la entrevista de voz. "
    "Recuerda que la llamada dura maximo 5 minutos."
)
_REJECT_REPLY = (
    "Entendido, respetamos tu decision. "
    "No te contactaremos por esta vacante. "
    "Si en algun momento cambias de opinion o tienes preguntas, estamos aqui."
)

# Turnos de historial (user+assistant) que se le pasan al modelo y se persisten —
# suficiente para que la conversacion fluya sin dejar crecer el prompt sin limite.
_MAX_HISTORY_TURNS = 20


class ProcessWhatsAppMessageUseCase:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ai = AsyncOpenAI(api_key=settings.openai_api_key)

    async def execute(self, from_phone: str, message_text: str) -> None:
        # Meta manda el "from" en solo dígitos (p.ej. "573147573205"), pero
        # Candidate.phone puede traer "+", espacios o guiones segun como lo
        # extrajo el parseo del CV (p.ej. "+57 314 757 3205") — comparamos
        # solo dígitos en ambos lados para no perder la coincidencia.
        digits_only = re.sub(r"\D", "", from_phone)
        stmt = (
            select(ProcessCandidate)
            .join(Candidate)
            .join(HiringProcess)
            .where(func.regexp_replace(Candidate.phone, r"\D", "", "g") == digits_only)
            .where(
                ProcessCandidate.whatsapp_consent_status.in_(
                    [
                        WhatsAppConsentStatus.PENDING.value,
                        WhatsAppConsentStatus.TIMEOUT.value,
                    ]
                )
            )
            .options(
                selectinload(ProcessCandidate.process),
                selectinload(ProcessCandidate.candidate),
            )
            .order_by(ProcessCandidate.created_at.desc())
        )
        result = await self.db.execute(stmt)
        pc = result.scalars().first()

        if not pc:
            # No dejar que un envio fallido (numero de prueba invalido, rate
            # limit, etc.) tumbe el webhook completo con 500 — Meta reintenta
            # webhooks que fallan, y ademas puede terminar deshabilitando la
            # suscripcion si ve fallos repetidos.
            try:
                await whatsapp_client.send_text_message(
                    to_phone=from_phone,
                    message=(
                        "Hola, gracias por escribirnos. "
                        "En este momento no tienes procesos de selección activos con Riwi. "
                        "Si crees que esto es un error, escríbenos a talent@riwi.io."
                    ),
                )
            except Exception as exc:
                logger.warning(f"[whatsapp] no se pudo responder a {from_phone}: {exc}")
            return

        candidate = pc.candidate
        process = pc.process

        # Clics de botón de la plantilla — respuesta directa sin pasar por IA
        button_intent = _resolve_button_intent(message_text)
        if button_intent:
            await self._apply_intent(pc, button_intent, None, from_phone, message_text)
            return

        system_prompt = _AGENT_SYSTEM_PROMPT.format(
            candidate_name=f"{candidate.name} {candidate.last_name}".strip(),
            job_title=process.job_title,
            consent_status=pc.whatsapp_consent_status,
        )

        history: list[dict[str, str]] = pc.whatsapp_conversation or []
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": message_text},
        ]

        ai_response = await self.ai.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        content = ai_response.choices[0].message.content or "{}"
        analysis = json.loads(content)

        intent: str = analysis.get("intent", "QUESTION")
        reply: str = analysis.get("reply_text", "")
        availability: dict | None = analysis.get("availability")

        await self._apply_intent(pc, intent, availability, from_phone, message_text, reply)

    async def _apply_intent(
        self,
        pc: ProcessCandidate,
        intent: str,
        availability: dict | None,
        from_phone: str,
        user_message: str,
        reply: str = "",
    ) -> None:
        if intent == "ACCEPTED":
            pc.whatsapp_consent_status = WhatsAppConsentStatus.ACCEPTED.value
            pc.whatsapp_responded_at = datetime.now(UTC)
            reply = reply or _ACCEPT_REPLY

            # El consentimiento por WhatsApp reemplaza la selección manual explícita
            # (RB-004) cuando el WhatsApp se disparó automáticamente tras el match —
            # sin este avance de estado, start_profiling_call falla siempre: la
            # transición a PROFILING_CALLING solo es válida desde PROFILING_QUEUED.
            try:
                status = CandidateStateMachine.transition(
                    CandidateStatus(pc.status), CandidateStatus.SELECTED_FOR_PROFILING
                )
                pc.status = CandidateStateMachine.transition(
                    status, CandidateStatus.PROFILING_QUEUED
                )
            except BusinessRuleException:
                pass  # ya en un estado de profiling en curso; no bloquear el consentimiento

            # Encolar la llamada a Twilio con el delay configurado (24h por defecto)
            from src.infrastructure.workers.tasks.profiling import start_profiling_call

            start_profiling_call.apply_async(
                args=[str(pc.id)], countdown=settings.profiling_delay_seconds
            )

        elif intent == "REJECTED":
            pc.whatsapp_consent_status = WhatsAppConsentStatus.REJECTED.value
            pc.whatsapp_responded_at = datetime.now(UTC)
            reply = reply or _REJECT_REPLY

        if availability and intent in ("ACCEPTED", "AVAILABILITY_ONLY"):
            pc.availability_preference = availability

        history = list(pc.whatsapp_conversation or [])
        history.append({"role": "user", "content": user_message})
        if reply:
            history.append({"role": "assistant", "content": reply})
        pc.whatsapp_conversation = history[-_MAX_HISTORY_TURNS:]

        await self.db.commit()

        if reply:
            # El estado ya quedo comiteado — un fallo de envio aqui no debe
            # revertir ni bloquear la transicion ya aplicada (RB-004/consentimiento).
            try:
                await whatsapp_client.send_text_message(to_phone=from_phone, message=reply)
            except Exception as exc:
                logger.warning(f"[whatsapp] no se pudo enviar la respuesta a {from_phone}: {exc}")
