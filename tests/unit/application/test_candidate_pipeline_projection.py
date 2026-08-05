from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from src.application.hiring_process.progress import (
    build_candidate_projection,
    build_candidate_projections,
)


def _candidate(status: str, updated_at: datetime):
    return SimpleNamespace(
        id="pc-1",
        candidate_id="candidate-1",
        status=status,
        whatsapp_consent_status="PENDING",
        created_at=updated_at,
        updated_at=updated_at,
    )


def _run(status: str, updated_at: datetime, suffix: str = "1"):
    return SimpleNamespace(
        id=f"run-{suffix}",
        process_candidate_id="pc-1",
        status=status,
        call_attempts=1,
        started_at=None,
        completed_at=None,
        created_at=updated_at,
        updated_at=updated_at,
        advancement_probability=None,
        twilio_status_detail=None,
    )


def test_pending_run_is_visible_as_waiting_for_consent_in_queue():
    now = datetime.now(UTC)
    projection = build_candidate_projection(
        _candidate("SELECTED_FOR_PROFILING", now), _run("PENDING", now)
    )

    assert projection.board_column == "QUEUED"
    assert projection.state_label == "Esperando consentimiento"
    assert projection.consistency == "OK"


def test_answered_run_uses_calling_column_and_detailed_label():
    now = datetime.now(UTC)
    projection = build_candidate_projection(
        _candidate("PROFILING_CALLING", now), _run("ANSWERED", now)
    )

    assert projection.board_column == "CALLING"
    assert projection.state_label == "Contestada"


def test_human_intent_after_terminal_run_is_preserved_as_attention():
    now = datetime.now(UTC)
    projection = build_candidate_projection(
        _candidate("PROFILING_QUEUED", now),
        _run("FAILED", now - timedelta(minutes=1)),
    )

    assert projection.board_column == "QUEUED"
    assert projection.consistency == "ATTENTION"
    assert projection.consistency_explanation == (
        "Ultimo intento fallido; sin corrida activa. Reintento manual requerido."
    )


def test_multiple_runs_still_produce_one_card_with_latest_attempt():
    now = datetime.now(UTC)
    projections = build_candidate_projections(
        [_candidate("PROFILING_COMPLETED", now)],
        [
            _run("FAILED", now - timedelta(days=1), "old"),
            _run("COMPLETED", now, "latest"),
        ],
    )

    assert len(projections) == 1
    assert projections[0].latest_run.id == "run-latest"
    assert projections[0].board_column == "COMPLETED"
