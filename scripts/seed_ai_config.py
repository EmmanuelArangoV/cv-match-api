"""
Siembra en la BD los prompts y modelos que hoy corren hardcodeados en código (src/infrastructure/
ai/prompts.py), como su primera versión activa, para que Admin > Parámetros de IA refleje lo que
realmente está en producción en vez de mostrarse vacío.

Idempotente: si una tarea ya tiene un prompt o modelo activo, se omite para esa tarea.

Incluye WHATSAPP_MESSAGE porque las respuestas conversacionales sí llaman a OpenAI. No incluye
un modelo para VOICE_CALL_AGENT: su prompt se inyecta al agente de ElevenLabs y el LLM de voz se
configura en ElevenLabs/QuestionSet, no en OpenAI.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from src.application.candidate.whatsapp_message_usecase import _AGENT_SYSTEM_PROMPT
from src.infrastructure.ai.prompts import (
    CV_EXTRACTION_PROMPT,
    JD_ANALYZE_ENHANCE_SYSTEM_PROMPT,
    MATCH_SYSTEM_PROMPT,
    PROFILING_EVALUATION_PROMPT,
    VOICE_CALL_AGENT_BASE_PROMPT,
)
from src.infrastructure.db.database import AsyncSessionFactory
from src.infrastructure.db.models import AIModelConfiguration, AIPrompt, AIProvider, AITaskType

PROMPTS = {
    AITaskType.CV_EXTRACTION: CV_EXTRACTION_PROMPT,
    AITaskType.CV_MATCH: MATCH_SYSTEM_PROMPT,
    AITaskType.JD_ENHANCEMENT: JD_ANALYZE_ENHANCE_SYSTEM_PROMPT,
    AITaskType.VOICE_PROFILING: PROFILING_EVALUATION_PROMPT,
    AITaskType.VOICE_CALL_AGENT: VOICE_CALL_AGENT_BASE_PROMPT,
    AITaskType.WHATSAPP_MESSAGE: _AGENT_SYSTEM_PROMPT,
}

MODELS = {
    AITaskType.CV_EXTRACTION: "gpt-5.6-luna",
    AITaskType.CV_MATCH: "gpt-5.6-luna",
    AITaskType.JD_ENHANCEMENT: "gpt-5.6-luna",
    AITaskType.VOICE_PROFILING: "gpt-5.6-luna",
    AITaskType.WHATSAPP_MESSAGE: "gpt-5.6-luna",
}


async def main() -> None:
    async with AsyncSessionFactory() as db:
        for task_type, prompt_text in PROMPTS.items():
            existing = await db.execute(
                select(AIPrompt).where(
                    AIPrompt.task_type == task_type.value, AIPrompt.is_active
                )
            )
            if existing.scalar_one_or_none():
                print(f"[{task_type.value}] ya tiene un prompt activo, se omite.")
                continue
            db.add(
                AIPrompt(
                    task_type=task_type.value,
                    version_name="v1-inicial",
                    system_prompt_text=prompt_text,
                    is_active=True,
                )
            )
            print(f"[{task_type.value}] prompt inicial creado y activado.")

        for task_type, model_name in MODELS.items():
            existing = await db.execute(
                select(AIModelConfiguration).where(
                    AIModelConfiguration.task_type == task_type.value,
                    AIModelConfiguration.provider == AIProvider.OPENAI.value,
                    AIModelConfiguration.is_active,
                )
            )
            if existing.scalar_one_or_none():
                print(f"[{task_type.value}] ya tiene un modelo activo, se omite.")
                continue
            db.add(
                AIModelConfiguration(
                    task_type=task_type.value,
                    provider=AIProvider.OPENAI.value,
                    model_name=model_name,
                    is_active=True,
                )
            )
            print(f"[{task_type.value}] modelo inicial ({model_name}) creado y activado.")

        await db.commit()

    print("\nListo.")


if __name__ == "__main__":
    asyncio.run(main())
