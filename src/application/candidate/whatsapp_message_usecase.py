import asyncio
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.config import settings
from src.infrastructure.db.models import ProcessCandidate, Candidate, WhatsAppConsentStatus, HiringProcess
from src.infrastructure.messaging.whatsapp_client import whatsapp_client

class ProcessWhatsAppMessageUseCase:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai = AsyncOpenAI(api_key=settings.openai_api_key)

    async def execute(self, from_phone: str, message_text: str):
        # 1. Buscar al candidato por teléfono
        # Si tiene varios procesos, tomamos el más reciente pendiente
        stmt = (
            select(ProcessCandidate)
            .join(Candidate)
            .join(HiringProcess)
            .where(Candidate.phone == from_phone)
            .where(ProcessCandidate.whatsapp_consent_status == WhatsAppConsentStatus.PENDING.value)
            .order_by(ProcessCandidate.created_at.desc())
        )
        result = await self.db.execute(stmt)
        pc = result.scalars().first()

        if not pc:
            # Si no hay proceso pendiente, respondemos amablemente
            await whatsapp_client.send_text_message(
                to_phone=from_phone, 
                message="Hola, no tienes procesos de selección activos pendientes de confirmación."
            )
            return

        process = await pc.awaitable_attrs.process
        candidate = await pc.awaitable_attrs.candidate

        # 2. Interpretar la intención y generar respuesta con IA
        system_prompt = f"""
        Eres un asistente de reclutamiento de RIWI MATCH. 
        El candidato {candidate.name} está aplicando para la vacante "{process.job_title}".
        Se le acaba de preguntar si acepta que un bot le llame para hacerle una entrevista automática.
        El candidato ha respondido esto: "{message_text}".
        
        Debes clasificar su intención y, si tiene preguntas sobre el cargo o el proceso, responderlas cordialmente.
        Si la intención es ACCEPTED, agradécele y dile que lo llamaremos pronto.
        Si la intención es REJECTED, despídete y confirma que no lo llamaremos.
        
        Devuelve estrictamente un JSON con esta estructura:
        {{
            "intent": "ACCEPTED" | "REJECTED" | "QUESTION",
            "reply_text": "El texto que le enviaremos de vuelta por WhatsApp respondiendo a lo que dijo",
            "availability": "Si mencionó alguna fecha u hora, escríbela aquí, si no, null"
        }}
        """

        ai_response = await self.ai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_prompt}],
            response_format={"type": "json_object"},
            temperature=0.3
        )

        import json
        analysis = json.loads(ai_response.choices[0].message.content)

        intent = analysis.get("intent")
        reply = analysis.get("reply_text")
        availability = analysis.get("availability")

        # 3. Actualizar la base de datos
        from datetime import datetime, timezone
        pc.whatsapp_responded_at = datetime.now(timezone.utc)

        if intent == "ACCEPTED":
            pc.whatsapp_consent_status = WhatsAppConsentStatus.ACCEPTED.value
        elif intent == "REJECTED":
            pc.whatsapp_consent_status = WhatsAppConsentStatus.REJECTED.value

        if availability:
            pc.availability_preference = {"note": availability}

        await self.db.commit()

        # 4. Enviar respuesta al candidato
        if reply:
            await whatsapp_client.send_text_message(to_phone=from_phone, message=reply)
