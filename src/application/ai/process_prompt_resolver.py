"""Resuelve prompts globales y revisiones de comunicacion propias del proceso."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.ai.prompts import (
    CV_EXTRACTION_PROMPT,
    JD_ANALYZE_ENHANCE_SYSTEM_PROMPT,
    MATCH_SYSTEM_PROMPT,
    PROFILING_EVALUATION_PROMPT,
    VOICE_CALL_AGENT_BASE_PROMPT,
)
from src.infrastructure.db.models import AIPrompt, AITaskType, ProcessAIPrompt

GLOBAL_RUNTIME_PROMPT_TASKS = (
    AITaskType.CV_EXTRACTION.value,
    AITaskType.CV_MATCH.value,
    AITaskType.JD_ENHANCEMENT.value,
    AITaskType.VOICE_PROFILING.value,
)
PROCESS_PROMPT_TASKS = (
    AITaskType.WHATSAPP_MESSAGE.value,
    AITaskType.VOICE_CALL_AGENT.value,
)


def _fallback_prompt(task_type: str) -> str:
    """Fallback de bootstrap; las operaciones normales nunca llegan aquí."""
    fallbacks = {
        AITaskType.CV_EXTRACTION.value: CV_EXTRACTION_PROMPT,
        AITaskType.CV_MATCH.value: MATCH_SYSTEM_PROMPT,
        AITaskType.JD_ENHANCEMENT.value: JD_ANALYZE_ENHANCE_SYSTEM_PROMPT,
        AITaskType.VOICE_PROFILING.value: PROFILING_EVALUATION_PROMPT,
        AITaskType.VOICE_CALL_AGENT.value: VOICE_CALL_AGENT_BASE_PROMPT,
    }
    if task_type == AITaskType.WHATSAPP_MESSAGE.value:
        # Import local para evitar que el flujo conversacional dependa de este resolver al cargar.
        from src.application.candidate.whatsapp_message_usecase import _AGENT_SYSTEM_PROMPT

        return _AGENT_SYSTEM_PROMPT
    return fallbacks[task_type]


async def seed_process_prompts(
    db: AsyncSession, process_id: uuid.UUID, created_by: uuid.UUID | None
) -> list[ProcessAIPrompt]:
    """Copia solo las plantillas de comunicacion que pertenecen al proceso."""
    templates = (
        (await db.execute(select(AIPrompt).where(AIPrompt.is_active.is_(True)))).scalars().all()
    )
    by_task = {str(template.task_type): template for template in templates}
    records: list[ProcessAIPrompt] = []
    for task_type in PROCESS_PROMPT_TASKS:
        template = by_task.get(task_type)
        record = ProcessAIPrompt(
            process_id=process_id,
            task_type=task_type,
            version_name=f"{template.version_name if template else 'v1-inicial'} · copia inicial",
            system_prompt_text=(
                template.system_prompt_text if template else _fallback_prompt(task_type)
            ),
            first_message_text=(
                template.first_message_text
                if template and task_type == AITaskType.VOICE_CALL_AGENT.value
                else None
            ),
            source_prompt_id=template.id if template else None,
            is_active=True,
            created_by=created_by,
        )
        db.add(record)
        records.append(record)
    await db.flush()
    return records


async def get_effective_prompt(
    db: AsyncSession, process_id: uuid.UUID, task_type: str
) -> AIPrompt | ProcessAIPrompt:
    prompt: AIPrompt | ProcessAIPrompt | None
    if task_type in GLOBAL_RUNTIME_PROMPT_TASKS:
        prompt = await db.scalar(
            select(AIPrompt).where(
                AIPrompt.task_type == task_type,
                AIPrompt.is_active.is_(True),
            )
        )
        scope = "global"
    elif task_type in PROCESS_PROMPT_TASKS:
        prompt = await db.scalar(
            select(ProcessAIPrompt).where(
                ProcessAIPrompt.process_id == process_id,
                ProcessAIPrompt.task_type == task_type,
                ProcessAIPrompt.is_active.is_(True),
            )
        )
        scope = "del proceso"
    else:
        raise BusinessRuleException(f"Tipo de prompt no soportado: {task_type}.")
    if not prompt:
        raise BusinessRuleException(
            f"No existe un prompt {scope} activo para {task_type}. "
            "Publica o restaura una plantilla antes de continuar."
        )
    return prompt


def get_effective_prompt_sync(
    db: Session, process_id: uuid.UUID, task_type: str
) -> AIPrompt | ProcessAIPrompt:
    prompt: AIPrompt | ProcessAIPrompt | None
    if task_type in GLOBAL_RUNTIME_PROMPT_TASKS:
        prompt = db.execute(
            select(AIPrompt).where(
                AIPrompt.task_type == task_type,
                AIPrompt.is_active.is_(True),
            )
        ).scalar_one_or_none()
        scope = "global"
    elif task_type in PROCESS_PROMPT_TASKS:
        prompt = db.execute(
            select(ProcessAIPrompt).where(
                ProcessAIPrompt.process_id == process_id,
                ProcessAIPrompt.task_type == task_type,
                ProcessAIPrompt.is_active.is_(True),
            )
        ).scalar_one_or_none()
        scope = "del proceso"
    else:
        raise BusinessRuleException(f"Tipo de prompt no soportado: {task_type}.")
    if not prompt:
        raise BusinessRuleException(
            f"No existe un prompt {scope} activo para {task_type}. "
            "Publica o restaura una plantilla antes de continuar."
        )
    return prompt


# Alias transitorios para consumidores externos; dentro del backend se usa el nombre
# explicito porque cuatro tareas ya no pertenecen al proceso.
get_process_prompt = get_effective_prompt
get_process_prompt_sync = get_effective_prompt_sync


async def next_process_prompt_version(
    db: AsyncSession, process_id: uuid.UUID, task_type: str
) -> str:
    count = await db.scalar(
        select(func.count(ProcessAIPrompt.id)).where(
            ProcessAIPrompt.process_id == process_id, ProcessAIPrompt.task_type == task_type
        )
    )
    return f"v{int(count or 0) + 1}-proceso"
