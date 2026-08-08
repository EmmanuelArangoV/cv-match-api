import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.v1.candidates import AnalysisContextBody, update_candidate_analysis_context
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import CandidateStatus, ProcessCandidate
from src.infrastructure.workers.tasks.parse_cv import _build_extraction_prompt


def _process_candidate(status: CandidateStatus) -> ProcessCandidate:
    return ProcessCandidate(
        id=uuid.uuid4(),
        process_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        status=status.value,
    )


@pytest.mark.asyncio
async def test_analysis_context_is_saved_for_pending_cv() -> None:
    pc = _process_candidate(CandidateStatus.LOADED)
    db = AsyncMock()
    db.add = MagicMock()
    recruiter = MagicMock(id=uuid.uuid4())

    with patch("src.api.v1.candidates.CandidateRepository") as repository:
        repository.return_value.find_process_candidate_by_id = AsyncMock(return_value=pc)
        response = await update_candidate_analysis_context(
            pc.process_id,
            pc.id,
            AnalysisContextBody(
                analysis_context="El nombre correcto es Ana Gómez; el teléfono no aparece en el CV."
            ),
            recruiter,
            db,
        )

    assert pc.analysis_context == (
        "El nombre correcto es Ana Gómez; el teléfono no aparece en el CV."
    )
    assert response == {"status": "updated", "analysis_context": pc.analysis_context}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_analysis_context_can_be_cleared_after_cv_error() -> None:
    pc = _process_candidate(CandidateStatus.CV_ERROR)
    pc.analysis_context = "Contexto anterior"
    db = AsyncMock()
    db.add = MagicMock()

    with patch("src.api.v1.candidates.CandidateRepository") as repository:
        repository.return_value.find_process_candidate_by_id = AsyncMock(return_value=pc)
        response = await update_candidate_analysis_context(
            pc.process_id,
            pc.id,
            AnalysisContextBody(analysis_context="   "),
            MagicMock(id=uuid.uuid4()),
            db,
        )

    assert pc.analysis_context is None
    assert response["analysis_context"] is None


@pytest.mark.asyncio
async def test_analysis_context_is_locked_once_analysis_started() -> None:
    pc = _process_candidate(CandidateStatus.CV_PROCESSING)
    db = AsyncMock()

    with patch("src.api.v1.candidates.CandidateRepository") as repository:
        repository.return_value.find_process_candidate_by_id = AsyncMock(return_value=pc)
        with pytest.raises(BusinessRuleException, match="solo se puede editar"):
            await update_candidate_analysis_context(
                pc.process_id,
                pc.id,
                AnalysisContextBody(analysis_context="No debería guardarse"),
                MagicMock(id=uuid.uuid4()),
                db,
            )

    db.commit.assert_not_awaited()


def test_extraction_prompt_keeps_default_prompt_without_context() -> None:
    assert _build_extraction_prompt("prompt base", None) == "prompt base"
    assert _build_extraction_prompt("prompt base", "   ") == "prompt base"


def test_extraction_prompt_adds_recruiter_context_with_priority_rules() -> None:
    prompt = _build_extraction_prompt("prompt base", "El nombre es Juan Pérez.")

    assert prompt.startswith("prompt base")
    assert "INFORMACIÓN ADICIONAL DEL RECRUITER" in prompt
    assert "El nombre es Juan Pérez." in prompt
    # La nota debe neutralizar explícitamente la regla "Never invent or guess data"
    # del prompt base — de lo contrario el modelo la trata como una invención y la
    # descarta, que era exactamente el bug reportado (la corrección no se aplicaba).
    assert "Never invent or guess data" in prompt
    assert "no una invención" in prompt
    assert "usa el valor de la nota" in prompt
