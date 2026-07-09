import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import RequireRecruiter, get_current_user
from src.domain.shared.exceptions import BusinessRuleException, NotFoundException
from src.infrastructure.db.database import get_db
from src.infrastructure.db.models import (
    ProfilingQuestion,
    QuestionSet,
    QuestionSetStatus,
    QuestionType,
    User,
)

router = APIRouter(prefix="/question-sets", tags=["Question Sets"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

VALID_QUESTION_TYPES = {qt.value for qt in QuestionType}
VALID_SET_STATUSES = {s.value for s in QuestionSetStatus}


class QuestionIn(BaseModel):
    order_index: int = 0
    text: str = Field(..., min_length=5)
    type: str = Field(default=QuestionType.OPEN.value)
    expected_answer: str | None = None
    positive_keywords: list[str] = []
    risk_keywords: list[str] = []
    weight: int = Field(default=10, ge=1, le=100)
    is_critical: bool = False
    eval_criteria: str | None = None

    def validate_type(self) -> None:
        if self.type not in VALID_QUESTION_TYPES:
            raise BusinessRuleException(
                f"Tipo de pregunta inválido: '{self.type}'. Valores válidos: {sorted(VALID_QUESTION_TYPES)}"
            )


class CreateQuestionSetRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    description: str | None = None
    questions: list[QuestionIn] = []


class UpdateQuestionSetRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None

    # Configuracion de voz (ElevenLabs) por defecto para procesos que usen este set.
    default_agent_id: str | None = None
    default_system_prompt: str | None = None
    default_first_message: str | None = None
    default_language: str | None = None
    default_llm_model: str | None = None
    default_voice_id: str | None = None
    default_tts_stability: float | None = None
    default_tts_speed: float | None = None
    default_tts_similarity_boost: float | None = None


class AddQuestionRequest(BaseModel):
    order_index: int = 0
    text: str = Field(..., min_length=5)
    type: str = Field(default=QuestionType.OPEN.value)
    expected_answer: str | None = None
    positive_keywords: list[str] = []
    risk_keywords: list[str] = []
    weight: int = Field(default=10, ge=1, le=100)
    is_critical: bool = False
    eval_criteria: str | None = None


class UpdateQuestionRequest(BaseModel):
    order_index: int | None = None
    text: str | None = None
    type: str | None = None
    expected_answer: str | None = None
    positive_keywords: list[str] | None = None
    risk_keywords: list[str] | None = None
    weight: int | None = None
    is_critical: bool | None = None
    eval_criteria: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_question(q: ProfilingQuestion) -> dict:
    return {
        "id": str(q.id),
        "question_set_id": str(q.question_set_id),
        "order_index": q.order_index,
        "text": q.text,
        "type": q.type,
        "expected_answer": q.expected_answer,
        "positive_keywords": q.positive_keywords or [],
        "risk_keywords": q.risk_keywords or [],
        "weight": q.weight,
        "is_critical": q.is_critical,
        "eval_criteria": q.eval_criteria,
    }


def _serialize_set(qs: QuestionSet, include_questions: bool = False) -> dict:
    data: dict = {
        "id": str(qs.id),
        "name": qs.name,
        "description": qs.description,
        "version": qs.version,
        "status": qs.status,
        "created_by": str(qs.created_by),
        "created_at": qs.created_at.isoformat(),
        "updated_at": qs.updated_at.isoformat(),
        "default_agent_id": qs.default_agent_id,
        "default_system_prompt": qs.default_system_prompt,
        "default_first_message": qs.default_first_message,
        "default_language": qs.default_language,
        "default_llm_model": qs.default_llm_model,
        "default_voice_id": qs.default_voice_id,
        "default_tts_stability": qs.default_tts_stability,
        "default_tts_speed": qs.default_tts_speed,
        "default_tts_similarity_boost": qs.default_tts_similarity_boost,
    }
    if include_questions:
        data["questions"] = [_serialize_question(q) for q in qs.questions]
    return data


async def _get_set_or_404(
    qs_id: uuid.UUID, db: AsyncSession, with_questions: bool = False
) -> QuestionSet:
    query = select(QuestionSet).where(QuestionSet.id == qs_id)
    if with_questions:
        query = query.options(selectinload(QuestionSet.questions))
    result = await db.execute(query)
    qs = result.scalar_one_or_none()
    if not qs:
        raise NotFoundException("Set de preguntas no encontrado")
    return qs


# ---------------------------------------------------------------------------
# Endpoints — Question Sets
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_question_set(
    body: CreateQuestionSetRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    qs = QuestionSet(
        name=body.name,
        description=body.description,
        version=1,
        status=QuestionSetStatus.DRAFT.value,
        created_by=current_user.id,
    )
    db.add(qs)
    await db.flush()  # genera el id antes de las preguntas

    for i, q in enumerate(body.questions):
        q.validate_type()
        pq = ProfilingQuestion(
            question_set_id=qs.id,
            order_index=q.order_index if q.order_index else i,
            text=q.text,
            type=q.type,
            expected_answer=q.expected_answer,
            positive_keywords=q.positive_keywords or [],
            risk_keywords=q.risk_keywords or [],
            weight=q.weight,
            is_critical=q.is_critical,
            eval_criteria=q.eval_criteria,
        )
        db.add(pq)

    await db.commit()
    await db.refresh(qs)

    result = await db.execute(
        select(QuestionSet)
        .where(QuestionSet.id == qs.id)
        .options(selectinload(QuestionSet.questions))
    )
    qs = result.scalar_one()
    return _serialize_set(qs, include_questions=True)


@router.get("")
async def list_question_sets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(QuestionSet)
        .options(selectinload(QuestionSet.questions))
        .order_by(QuestionSet.created_at.desc())
    )
    sets = list(result.scalars().all())
    return {
        "total": len(sets),
        "question_sets": [_serialize_set(qs, include_questions=True) for qs in sets],
    }


@router.get("/{question_set_id}")
async def get_question_set(
    question_set_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    qs = await _get_set_or_404(question_set_id, db, with_questions=True)
    return _serialize_set(qs, include_questions=True)


@router.patch("/{question_set_id}")
async def update_question_set(
    question_set_id: uuid.UUID,
    body: UpdateQuestionSetRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    qs = await _get_set_or_404(question_set_id, db, with_questions=True)
    qs = await _clone_question_set_if_active(qs, db)

    if body.name is not None:
        qs.name = body.name
    if body.description is not None:
        qs.description = body.description
    if body.status is not None:
        if body.status not in VALID_SET_STATUSES:
            raise BusinessRuleException(
                f"Estado inválido: '{body.status}'. Valores válidos: {sorted(VALID_SET_STATUSES)}"
            )
        qs.status = body.status

    for field in (
        "default_agent_id",
        "default_system_prompt",
        "default_first_message",
        "default_language",
        "default_llm_model",
        "default_voice_id",
        "default_tts_stability",
        "default_tts_speed",
        "default_tts_similarity_boost",
    ):
        value = getattr(body, field)
        if value is not None:
            setattr(qs, field, value)

    await db.commit()
    await db.refresh(qs)
    return _serialize_set(qs)


@router.delete("/{question_set_id}", status_code=204)
async def delete_question_set(
    question_set_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> None:
    qs = await _get_set_or_404(question_set_id, db)
    await db.delete(qs)
    await db.commit()


# ---------------------------------------------------------------------------
# Endpoints — Questions dentro de un set
# ---------------------------------------------------------------------------


@router.post("/{question_set_id}/questions", status_code=201)
async def add_question(
    question_set_id: uuid.UUID,
    body: AddQuestionRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    qs = await _get_set_or_404(question_set_id, db, with_questions=True)
    qs = await _clone_question_set_if_active(qs, db)

    if body.type not in VALID_QUESTION_TYPES:
        raise BusinessRuleException(
            f"Tipo de pregunta inválido: '{body.type}'. Valores válidos: {sorted(VALID_QUESTION_TYPES)}"
        )

    # Auto order_index si no viene
    next_index = max((q.order_index for q in qs.questions), default=-1) + 1

    pq = ProfilingQuestion(
        question_set_id=qs.id,
        order_index=body.order_index if body.order_index else next_index,
        text=body.text,
        type=body.type,
        expected_answer=body.expected_answer,
        positive_keywords=body.positive_keywords or [],
        risk_keywords=body.risk_keywords or [],
        weight=body.weight,
        is_critical=body.is_critical,
        eval_criteria=body.eval_criteria,
    )
    db.add(pq)
    await db.commit()
    await db.refresh(pq)
    return _serialize_question(pq)


@router.patch("/{question_set_id}/questions/{question_id}")
async def update_question(
    question_set_id: uuid.UUID,
    question_id: uuid.UUID,
    body: UpdateQuestionRequest,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(ProfilingQuestion).where(
            ProfilingQuestion.id == question_id,
            ProfilingQuestion.question_set_id == question_set_id,
        )
    )
    original_pq: ProfilingQuestion | None = result.scalar_one_or_none()
    if not original_pq:
        raise NotFoundException("Pregunta no encontrada")

    qs = await _get_set_or_404(question_set_id, db, with_questions=True)
    qs = await _clone_question_set_if_active(qs, db)

    pq = next((q for q in qs.questions if q.id == original_pq.id), None)
    if not pq:
        pq = next(
            (
                q
                for q in qs.questions
                if q.text == original_pq.text and q.order_index == original_pq.order_index
            ),
            None,
        )
        if not pq:
            raise NotFoundException("Pregunta no encontrada tras versionamiento")

    if body.order_index is not None:
        pq.order_index = body.order_index
    if body.text is not None:
        pq.text = body.text
    if body.type is not None:
        if body.type not in VALID_QUESTION_TYPES:
            raise BusinessRuleException(
                f"Tipo de pregunta inválido: '{body.type}'. Valores válidos: {sorted(VALID_QUESTION_TYPES)}"
            )
        pq.type = body.type
    if body.expected_answer is not None:
        pq.expected_answer = body.expected_answer
    if body.positive_keywords is not None:
        pq.positive_keywords = body.positive_keywords
    if body.risk_keywords is not None:
        pq.risk_keywords = body.risk_keywords
    if body.weight is not None:
        pq.weight = body.weight
    if body.is_critical is not None:
        pq.is_critical = body.is_critical
    if body.eval_criteria is not None:
        pq.eval_criteria = body.eval_criteria

    await db.commit()
    await db.refresh(pq)
    return _serialize_question(pq)


@router.delete("/{question_set_id}/questions/{question_id}", status_code=204)
async def delete_question(
    question_set_id: uuid.UUID,
    question_id: uuid.UUID,
    current_user: User = RequireRecruiter,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(ProfilingQuestion).where(
            ProfilingQuestion.id == question_id,
            ProfilingQuestion.question_set_id == question_set_id,
        )
    )
    original_pq: ProfilingQuestion | None = result.scalar_one_or_none()
    if not original_pq:
        raise NotFoundException("Pregunta no encontrada")

    qs = await _get_set_or_404(question_set_id, db, with_questions=True)
    qs = await _clone_question_set_if_active(qs, db)

    pq = next((q for q in qs.questions if q.id == original_pq.id), None)
    if not pq:
        pq = next(
            (
                q
                for q in qs.questions
                if q.text == original_pq.text and q.order_index == original_pq.order_index
            ),
            None,
        )
        if not pq:
            raise NotFoundException("Pregunta no encontrada tras versionamiento")
    await db.delete(pq)
    await db.commit()


async def _clone_question_set_if_active(qs: QuestionSet, db: AsyncSession) -> QuestionSet:
    from sqlalchemy import select

    from src.infrastructure.db.models import HiringProcess, ProfilingQuestion, QuestionSetStatus

    in_use = await db.execute(
        select(HiringProcess.id).where(HiringProcess.question_set_id == qs.id).limit(1)
    )
    is_in_use = in_use.scalar_one_or_none() is not None

    if qs.status == QuestionSetStatus.ACTIVE.value or is_in_use:
        new_qs = QuestionSet(
            name=qs.name,
            description=qs.description,
            version=qs.version + 1,
            status=QuestionSetStatus.DRAFT.value,
            created_by=qs.created_by,
            default_agent_id=qs.default_agent_id,
            default_system_prompt=qs.default_system_prompt,
            default_first_message=qs.default_first_message,
            default_language=qs.default_language,
            default_llm_model=qs.default_llm_model,
            default_voice_id=qs.default_voice_id,
            default_tts_stability=qs.default_tts_stability,
            default_tts_speed=qs.default_tts_speed,
            default_tts_similarity_boost=qs.default_tts_similarity_boost,
        )
        db.add(new_qs)
        await db.flush()  # get new_qs.id

        # Clone questions
        for q in qs.questions:
            new_q = ProfilingQuestion(
                question_set_id=new_qs.id,
                order_index=q.order_index,
                text=q.text,
                type=q.type,
                expected_answer=q.expected_answer,
                positive_keywords=list(q.positive_keywords) if q.positive_keywords else [],
                risk_keywords=list(q.risk_keywords) if q.risk_keywords else [],
                weight=q.weight,
                is_critical=q.is_critical,
                eval_criteria=q.eval_criteria,
            )
            db.add(new_q)

        await db.flush()
        # Refresh the new_qs to have the questions loaded
        result = await db.execute(
            select(QuestionSet)
            .where(QuestionSet.id == new_qs.id)
            .options(selectinload(QuestionSet.questions))
        )
        return result.scalar_one()

    return qs
