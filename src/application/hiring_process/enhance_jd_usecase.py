"""
Caso de uso para mejorar la Job Description con IA.
"""

from __future__ import annotations

import json

from openai import AsyncOpenAI

from src.config import settings
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.ai.prompts import build_jd_enhance_messages


class EnhanceJDUseCase:
    def __init__(self) -> None:
        self.ai = AsyncOpenAI(api_key=settings.openai_api_key)

    async def execute(self, raw_text: str) -> dict:
        try:
            response = await self.ai.chat.completions.create(
                model="gpt-4o",
                messages=build_jd_enhance_messages(raw_text),
                response_format={"type": "json_object"},
                temperature=0.6,
            )
        except Exception as exc:
            raise BusinessRuleException(
                f"No se pudo mejorar la Job Description con IA: {exc}"
            ) from exc

        content = response.choices[0].message.content or "{}"
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise BusinessRuleException(
                "La IA devolvio una respuesta invalida al mejorar la Job Description."
            ) from exc

        return {
            "enhanced_jd": result.get("enhanced_jd", raw_text),
            "recommendations": result.get("recommendations", []),
            "missing_elements": result.get("missing_elements", []),
        }
