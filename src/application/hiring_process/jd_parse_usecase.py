"""
Caso de uso de analisis + enriquecimiento de Job Description con IA, en una sola llamada.

Es analisis puro: no persiste nada (la persistencia de la JD sigue pasando por
CreateJobDescriptionRequest / saveJD, tal como hoy). El recruiter revisa el
resultado estructurado (requisitos extraidos + version mejorada sugerida) antes
de decidir aplicarlo y guardarlo.
"""

from __future__ import annotations

import json

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.ai.prompts import (
    JD_ANALYZE_ENHANCE_SYSTEM_PROMPT,
    build_jd_analyze_enhance_messages,
)
from src.infrastructure.cache.redis_client import get_active_ai_model, get_active_ai_prompt


class ParseJobDescriptionUseCase:
    def __init__(self) -> None:
        self.ai = AsyncOpenAI(api_key=settings.openai_api_key)

    async def execute(
        self,
        db: AsyncSession,
        raw_text: str,
        process_name: str,
        job_title: str,
        area: str,
        seniority: str,
    ) -> dict:
        # Prompt y modelo activos (configurables desde ajustes), con fallback al default de código
        system_prompt = await get_active_ai_prompt(
            db, "JD_ENHANCEMENT", JD_ANALYZE_ENHANCE_SYSTEM_PROMPT
        )
        model = await get_active_ai_model(db, "JD_ENHANCEMENT", "OPENAI", "gpt-4o")

        try:
            response = await self.ai.chat.completions.create(
                model=model,
                messages=build_jd_analyze_enhance_messages(
                    raw_text,
                    process_name,
                    job_title,
                    area,
                    seniority,
                    system_prompt=system_prompt,
                ),
                response_format={"type": "json_object"},
                temperature=0.4,
            )
        except Exception as exc:
            raise BusinessRuleException(
                f"No se pudo analizar la Job Description con IA: {exc}"
            ) from exc

        content = response.choices[0].message.content or "{}"
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise BusinessRuleException(
                "La IA devolvio una respuesta invalida al analizar la Job Description."
            ) from exc

        return {
            "must_have": result.get("must_have", []),
            "nice_to_have": result.get("nice_to_have", []),
            "deal_breakers": result.get("deal_breakers", []),
            "summary": result.get("summary", ""),
            "enhanced_jd": result.get("enhanced_jd", raw_text),
            "recommendations": result.get("recommendations", []),
            "missing_elements": result.get("missing_elements", []),
        }
