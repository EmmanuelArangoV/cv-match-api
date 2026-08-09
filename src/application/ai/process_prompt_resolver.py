"""Resuelve y versiona prompts que pertenecen exclusivamente a un proceso."""

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

PROCESS_PROMPT_TASKS = tuple(task.value for task in AITaskType)


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
    """Copia las plantillas activas para que el proceso no las herede en runtime."""
    templates = (
        await db.execute(select(AIPrompt).where(AIPrompt.is_active.is_(True)))
    ).scalars().all()
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
            source_prompt_id=template.id if template else None,
            is_active=True,
            created_by=created_by,
        )
        db.add(record)
        records.append(record)
    await db.flush()
    return records


async def get_process_prompt(
    db: AsyncSession, process_id: uuid.UUID, task_type: str
) -> ProcessAIPrompt:
    prompt = await db.scalar(
        select(ProcessAIPrompt).where(
            ProcessAIPrompt.process_id == process_id,
            ProcessAIPrompt.task_type == task_type,
            ProcessAIPrompt.is_active.is_(True),
        )
    )
    if not prompt:
        raise BusinessRuleException(
            f"El proceso no tiene un prompt activo para {task_type}. "
            "Restaura una plantilla antes de continuar."
        )
    return prompt


def get_process_prompt_sync(
    db: Session, process_id: uuid.UUID, task_type: str
) -> ProcessAIPrompt:
    prompt = db.execute(
        select(ProcessAIPrompt).where(
            ProcessAIPrompt.process_id == process_id,
            ProcessAIPrompt.task_type == task_type,
            ProcessAIPrompt.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if not prompt:
        raise BusinessRuleException(
            f"El proceso no tiene un prompt activo para {task_type}. "
            "Restaura una plantilla antes de continuar."
        )
    return prompt


async def next_process_prompt_version(
    db: AsyncSession, process_id: uuid.UUID, task_type: str
) -> str:
    count = await db.scalar(
        select(func.count(ProcessAIPrompt.id)).where(
            ProcessAIPrompt.process_id == process_id, ProcessAIPrompt.task_type == task_type
        )
    )
    return f"v{int(count or 0) + 1}-proceso"
