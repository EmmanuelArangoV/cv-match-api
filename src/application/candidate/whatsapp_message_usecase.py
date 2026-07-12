from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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

Esta conversación tiene memoria: los turnos anteriores del chat (tuyos y del candidato) se te pasan
como historial real antes del último mensaje — úsalos para no repetir preguntas ya respondidas ni
perder el hilo. El último mensaje del usuario en la conversación es el que debes responder ahora.

IMPORTANTE — alcance de tu memoria: solo tienes el historial de ESTA solicitud/proceso puntual
({job_title}). No tienes contexto de otras vacantes, procesos anteriores, ni conversaciones previas
de este candidato con Riwi fuera de este chat. Si el candidato pregunta por otro proceso, se refiere
a una aplicación distinta, o asume que recuerdas algo de antes de este chat, acláraselo
explícitamente: no tienes esa información, solo la de este proceso puntual.

═══ CONTEXTO DE ESTA CONVERSACIÓN ═══
Candidato: {candidate_name}
Cargo al que aplica: {job_title}
Empresa: Riwi Corp
Estado actual de consentimiento: {consent_status}

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

SOBRE LA EMPRESA (Riwi Corp):
- SÍ puedes dar contexto general sobre Riwi Corp si lo preguntan (a qué se dedica, cultura, etc.),
  usando solo la información de este prompt — no inventes datos que no tengas aquí.

SOBRE SALARIO, BENEFICIOS Y CONDICIONES DEL CARGO:
- NO tienes autorizado dar información sobre aspiración salarial, rango salarial, beneficios del
  cargo (bonos, seguro, vacaciones, horario, modalidad de trabajo, etc.) ni ningún detalle de la
  oferta más allá de lo que ya está en este prompt.
- Si el candidato pregunta por esto, responde con calidez que esa información se comparte en una
  etapa más avanzada del proceso, directamente con el equipo de Talent Acquisition — no en este chat.
- No inventes ni aproximes cifras ni condiciones aunque el candidato insista o pregunte varias veces.

SI EL CANDIDATO YA ACEPTÓ (estado de consentimiento ACCEPTED) Y SOLO ESTÁ PREGUNTANDO:
- No le vuelvas a pedir que acepte ni repitas el flujo de consentimiento — ya quedó registrado.
- Clasifica su mensaje como QUESTION y respóndele directo con la info que pide.

═══ TONO Y LÍMITES ESTRICTOS ═══
- Cercano pero profesional (tuteo está bien)
- Mensajes cortos (WhatsApp, no email)
- Sin emojis excesivos — máximo 1 por mensaje si aplica
- Si el candidato está preocupado por sus datos, sé especialmente empático y detallado
- ERES UN ASISTENTE DE RECLUTAMIENTO, NO UN ASISTENTE GENERAL.
- Si el candidato hace preguntas FUERA de contexto (ej. religión, historia, política, programación general, Salmo 23, chistes), DEBES NEGARTE amablemente a responder.
- Si está fuera de contexto, responde algo como: "Disculpa, solo estoy configurado para ayudarte con dudas sobre tu proceso de selección en Riwi Corp. ¿Tienes alguna pregunta sobre la entrevista?"
- NUNCA des cifras, rangos o promesas de salario ni detalles de beneficios/condiciones del cargo — remite siempre esas preguntas a una etapa posterior del proceso con el equipo humano (ver sección de FAQ correspondiente).
- SOLO tienes memoria de esta solicitud puntual — nunca actúes como si recordaras otro proceso o vacante distinta a {job_title}.

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
    "Recuerda que la llamada dura maximo 5 minutos. "
    "Si tienes alguna duda mientras tanto, escribeme aqui mismo y con gusto te respondo."
)
_REJECT_REPLY = (
    "Entendido, respetamos tu decision. "
    "No te contactaremos por esta vacante. "
    "Si en algun momento cambias de opinion o tienes preguntas, estamos aqui."
)

# Cuantos turnos (usuario + asistente, ya intercalados) del historial se le pasan
# de vuelta al modelo como contexto — tope simple para no disparar tokens de mas.
_MAX_HISTORY_TURNS = 20

# ═══ GUARDRAIL DURO: salario/beneficios ═══
# El prompt ya le prohibe al modelo hablar de esto, pero un LLM puede fallar o ser
# manipulado (prompt injection del propio candidato) — esta es la ultima linea de
# defensa a nivel de codigo: escanea CUALQUIER respuesta saliente (sin importar el
# intent ni si vino de la IA o de una constante) y la reemplaza si detecta cifras de
# dinero o vocabulario de compensacion/beneficios, sin excepciones.
_COMPENSATION_KEYWORDS = (
    "salario",
    "sueldo",
    "remuneracion",
    "remuneración",
    "aspiracion salarial",
    "aspiración salarial",
    "rango salarial",
    "compensacion",
    "compensación",
    "beneficio",
    "prestacion",
    "prestación",
    "prestaciones",
    "prima",
    "bonificacion",
    "bonificación",
    "bono",
    "seguro medico",
    "seguro médico",
    " eps",
    " arl",
    "cesantia",
    "cesantía",
    "auxilio de transporte",
    "vacaciones pagadas",
    "salario emocional",
    "smlv",
    "salario minimo",
    "salario mínimo",
)

_MONEY_PATTERN = re.compile(
    r"\$\s?\d"  # $3.000.000, $ 3000000
    r"|\bcop\b"  # COP
    r"|\busd\b"  # USD
    r"|\d[\d.,]{2,}\s?(pesos|d[oó]lares)"  # 3.000.000 pesos / 3000 dolares
    r"|\b\d+\s?(mill[oó]n(es)?)\b",  # 3 millones / 1 millon
    re.IGNORECASE,
)

_COMPENSATION_DEFERRAL_REPLY = (
    "Esa informacion (salario, beneficios y condiciones del cargo) se comparte mas "
    "adelante en el proceso, directamente con el equipo de Talent Acquisition. Por "
    "ahora puedo ayudarte con dudas sobre la entrevista de voz o sobre Riwi Corp en "
    "general."
)


def _violates_compensation_policy(text: str) -> bool:
    normalized = f" {text.lower()} "
    if _MONEY_PATTERN.search(normalized):
        return True
    return any(keyword in normalized for keyword in _COMPENSATION_KEYWORDS)


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
                        # Tambien despues de responder: el chat sigue siendo conversacional
                        # (dudas post-aceptacion, cambio de opinion post-rechazo, etc.) —
                        # order_by + first() ya garantiza que tomamos el proceso mas reciente
                        # de este telefono, que es "el ultimo contacto" del aspirante.
                        WhatsAppConsentStatus.ACCEPTED.value,
                        WhatsAppConsentStatus.REJECTED.value,
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
        # Historial previo de ESTE proceso puntual — vive en la fila de ProcessCandidate,
        # asi que si el mismo telefono aplica a otra vacante despues, esa fila es nueva y
        # el contexto arranca limpio (ver comentario en el modelo).
        history: list[dict] = list(pc.whatsapp_conversation or [])

        # Clics de botón (plantilla o interactivo) — respuesta directa sin pasar por IA
        button_intent = _resolve_button_intent(message_text)
        if button_intent:
            await self._apply_intent(
                pc, button_intent, None, from_phone, history=history, user_text=message_text
            )
            return

        system_prompt = _AGENT_SYSTEM_PROMPT.format(
            candidate_name=f"{candidate.name} {candidate.last_name}".strip(),
            job_title=process.job_title,
            consent_status=pc.whatsapp_consent_status,
        )
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt}
        ]
        for turn in history[-_MAX_HISTORY_TURNS:]:
            turn_text = str(turn.get("text", ""))
            if turn.get("role") == "assistant":
                messages.append({"role": "assistant", "content": turn_text})
            else:
                messages.append({"role": "user", "content": turn_text})
        messages.append({"role": "user", "content": message_text})

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

        await self._apply_intent(
            pc, intent, availability, from_phone, reply, history=history, user_text=message_text
        )

    async def _apply_intent(
        self,
        pc: ProcessCandidate,
        intent: str,
        availability: dict | None,
        from_phone: str,
        reply: str = "",
        *,
        history: list[dict],
        user_text: str,
    ) -> None:
        already_accepted = pc.whatsapp_consent_status == WhatsAppConsentStatus.ACCEPTED.value

        if intent == "ACCEPTED":
            pc.whatsapp_consent_status = WhatsAppConsentStatus.ACCEPTED.value
            pc.whatsapp_responded_at = datetime.now(UTC)
            reply = reply or _ACCEPT_REPLY

            # El consentimiento por WhatsApp reemplaza la selección manual explícita
            # (RB-004) cuando el WhatsApp se disparó automáticamente tras el match —
            # sin este avance de estado, start_profiling_call falla siempre: la
            # transición a PROFILING_CALLING solo es válida desde PROFILING_QUEUED.
            # El chat ahora sigue conversacional despues de ACCEPTED (para que el
            # candidato pueda seguir preguntando) — si la IA vuelve a clasificar un
            # mensaje posterior como ACCEPTED (p.ej. una afirmacion suelta), no hay
            # que repetir la transicion de estado ni volver a encolar la llamada.
            if not already_accepted:
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

            # Rechazo explicito: sacarlo de la cola para que nunca se le llame.
            if pc.status == CandidateStatus.PROFILING_QUEUED.value:
                pc.status = CandidateStateMachine.transition(
                    CandidateStatus(pc.status), CandidateStatus.SELECTED_FOR_PROFILING
                ).value

        if availability and intent in ("ACCEPTED", "AVAILABILITY_ONLY"):
            pc.availability_preference = availability

        # Guardrail duro: pase lo que pase arriba (IA o constante), esta respuesta
        # NUNCA sale con cifras de dinero ni vocabulario de salario/beneficios.
        if reply and _violates_compensation_policy(reply):
            logger.warning(
                f"[whatsapp] respuesta bloqueada por guardrail de compensacion "
                f"(pc={pc.id}, intent={intent}): {reply!r}"
            )
            reply = _COMPENSATION_DEFERRAL_REPLY

        # Nueva lista (no mutar in-place) para que SQLAlchemy detecte el cambio en la
        # columna JSONB y lo incluya en el UPDATE.
        updated_history = [*history, {"role": "user", "text": user_text, "at": _now_iso()}]
        if reply:
            updated_history.append({"role": "assistant", "text": reply, "at": _now_iso()})
        pc.whatsapp_conversation = updated_history[-_MAX_HISTORY_TURNS:]

        await self.db.commit()

        if reply:
            # El estado ya quedo comiteado — un fallo de envio aqui no debe
            # revertir ni bloquear la transicion ya aplicada (RB-004/consentimiento).
            try:
                await whatsapp_client.send_text_message(to_phone=from_phone, message=reply)
            except Exception as exc:
                logger.warning(f"[whatsapp] no se pudo enviar la respuesta a {from_phone}: {exc}")
