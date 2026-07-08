import pytest

from src.domain.candidate.state_machine import CandidateStateMachine
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import CandidateStatus


def test_profiling_queued_can_transition_to_profiling_failed():
    """Caso: consentimiento de WhatsApp resuelto como REJECTED con un ProfilingRun en cola."""
    result = CandidateStateMachine.transition(
        CandidateStatus.PROFILING_QUEUED, CandidateStatus.PROFILING_FAILED
    )
    assert result == CandidateStatus.PROFILING_FAILED


def test_profiling_queued_can_still_transition_to_calling():
    result = CandidateStateMachine.transition(
        CandidateStatus.PROFILING_QUEUED, CandidateStatus.PROFILING_CALLING
    )
    assert result == CandidateStatus.PROFILING_CALLING


def test_profiling_completed_is_terminal():
    with pytest.raises(BusinessRuleException):
        CandidateStateMachine.transition(
            CandidateStatus.PROFILING_COMPLETED, CandidateStatus.PROFILING_FAILED
        )


def test_invalid_transition_raises():
    with pytest.raises(BusinessRuleException):
        CandidateStateMachine.transition(
            CandidateStatus.LOADED, CandidateStatus.PROFILING_COMPLETED
        )
