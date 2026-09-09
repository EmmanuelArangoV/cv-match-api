"""Set base de profiling para el primer acercamiento telefónico.

El set se conserva como plantilla ACTIVE. Cada proceso recibe una copia independiente,
por lo que cambiar sus preguntas no modifica la versión que se preselecciona después.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.infrastructure.db.models import (
    ProfilingQuestion,
    QuestionSet,
    QuestionSetStatus,
    QuestionType,
)

DEFAULT_FIRST_CONTACT_QUESTION_SET_ID = uuid.UUID("b6f1f0e7-6167-4d74-9f2b-2c9493022051")
DEFAULT_FIRST_CONTACT_QUESTION_SET_NAME = (
    "PROFILING TELEFÓNICO DE PRIMER ACERCAMIENTO — GENÉRICO (+ HABITUAL)"
)
DEFAULT_FIRST_CONTACT_QUESTION_SET_DESCRIPTION = (
    "Cuestionario predeterminado para la primera llamada de profiling. "
    "Cada proceso recibe una copia editable de esta plantilla."
)


@dataclass(frozen=True)
class DefaultQuestion:
    order_index: int
    text: str
    type: QuestionType
    expected_answer: str
    is_critical: bool = False
    positive_keywords: tuple[str, ...] = ()
    risk_keywords: tuple[str, ...] = ()
    eval_criteria: str | None = None


DEFAULT_FIRST_CONTACT_QUESTIONS: tuple[DefaultQuestion, ...] = (
    DefaultQuestion(
        order_index=0,
        text=(
            "¿Qué modalidad de trabajo se ajusta mejor a tu disponibilidad actual: remoto, "
            "híbrido o presencial?"
        ),
        type=QuestionType.MULTIPLE_CHOICE,
        expected_answer="Remoto, híbrido, presencial o una combinación de estas modalidades.",
    ),
    DefaultQuestion(
        order_index=1,
        text="¿Cómo describirías tu nivel actual de inglés: básico, intermedio o avanzado?",
        type=QuestionType.MULTIPLE_CHOICE,
        expected_answer="Básico, intermedio o avanzado.",
    ),
    DefaultQuestion(
        order_index=2,
        text=(
            "¿Cuál es tu expectativa salarial para esta oportunidad? Indícame el valor y la "
            "moneda que esperas."
        ),
        type=QuestionType.CLOSED,
        expected_answer="Valor y moneda de la expectativa salarial.",
    ),
    DefaultQuestion(
        order_index=3,
        text=(
            "¿Qué disponibilidad tienes para vincularte a un nuevo equipo: inmediata, dentro "
            "de una a dos semanas o después de ese periodo?"
        ),
        type=QuestionType.MULTIPLE_CHOICE,
        expected_answer="Inmediata, dentro de una a dos semanas o después de ese periodo.",
    ),
    DefaultQuestion(
        order_index=4,
        text=(
            "Para entender tu disponibilidad de forma realista, ¿hay algún compromiso personal, "
            "familiar, académico u otro que pueda afectar tu vinculación durante los próximos "
            "tres meses?"
        ),
        type=QuestionType.OPEN,
        expected_answer=(
            "Explicación breve de cualquier compromiso y de su posible impacto, si aplica."
        ),
    ),
)


async def get_or_create_default_first_contact_question_set(
    db: AsyncSession, *, created_by: uuid.UUID
) -> QuestionSet:
    """Obtiene la plantilla base o la crea de forma diferida en bases nuevas."""
    result = await db.execute(
        select(QuestionSet)
        .where(QuestionSet.id == DEFAULT_FIRST_CONTACT_QUESTION_SET_ID)
        .options(selectinload(QuestionSet.questions))
    )
    question_set = result.scalar_one_or_none()
    if question_set:
        return question_set

    question_set = QuestionSet(
        id=DEFAULT_FIRST_CONTACT_QUESTION_SET_ID,
        name=DEFAULT_FIRST_CONTACT_QUESTION_SET_NAME,
        description=DEFAULT_FIRST_CONTACT_QUESTION_SET_DESCRIPTION,
        version=1,
        status=QuestionSetStatus.ACTIVE.value,
        created_by=created_by,
    )
    question_set.questions = [
        ProfilingQuestion(
            order_index=question.order_index,
            text=question.text,
            type=question.type.value,
            expected_answer=question.expected_answer,
            positive_keywords=list(question.positive_keywords),
            risk_keywords=list(question.risk_keywords),
            weight=10,
            is_critical=question.is_critical,
            eval_criteria=question.eval_criteria,
        )
        for question in DEFAULT_FIRST_CONTACT_QUESTIONS
    ]
    db.add(question_set)
    await db.flush()
    return question_set
