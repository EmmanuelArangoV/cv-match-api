from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.application.profiling.lifecycle import apply_profiling_transition
from src.domain.profiling.state_machine import ProfilingRunStateMachine
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import ProfilingRunStatus


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ProfilingRunStatus.PENDING, ProfilingRunStatus.QUEUED),
        (ProfilingRunStatus.PENDING, ProfilingRunStatus.CANCELLED),
        (ProfilingRunStatus.QUEUED, ProfilingRunStatus.CALLING),
        (ProfilingRunStatus.CALLING, ProfilingRunStatus.ANSWERED),
        (ProfilingRunStatus.CALLING, ProfilingRunStatus.RETRY_PENDING),
        (ProfilingRunStatus.RETRY_PENDING, ProfilingRunStatus.QUEUED),
        (ProfilingRunStatus.ANSWERED, ProfilingRunStatus.COMPLETED),
    ],
)
def test_valid_profiling_run_transitions(current, target):
    assert ProfilingRunStateMachine.transition(current, target) == target


@pytest.mark.parametrize(
    "terminal",
    [
        ProfilingRunStatus.COMPLETED,
        ProfilingRunStatus.FAILED,
        ProfilingRunStatus.NO_ANSWER,
        ProfilingRunStatus.VOICEMAIL_DETECTED,
        ProfilingRunStatus.CANCELLED,
    ],
)
def test_terminal_profiling_runs_reject_late_callbacks(terminal):
    with pytest.raises(BusinessRuleException):
        ProfilingRunStateMachine.transition(terminal, ProfilingRunStatus.COMPLETED)


def test_publication_failure_aligns_selected_candidate_without_skipping_state_machine():
    now = datetime.now(UTC)
    run = SimpleNamespace(
        status="PENDING",
        started_at=None,
        completed_at=None,
        twilio_status_detail=None,
    )
    candidate = SimpleNamespace(status="SELECTED_FOR_PROFILING")

    apply_profiling_transition(
        run,
        candidate,
        ProfilingRunStatus.FAILED,
        now=now,
        detail="publish_failed",
    )

    assert run.status == "FAILED"
    assert run.completed_at == now
    assert candidate.status == "PROFILING_FAILED"
