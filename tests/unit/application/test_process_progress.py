from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from src.application.hiring_process.progress import (
    build_process_progress,
    derive_process_stage,
)


def _process(status="DRAFT", question_set_id=None):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id="process-1",
        status=status,
        question_set_id=question_set_id,
        created_at=now,
        updated_at=now,
    )


def _candidate(status, candidate_id):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=candidate_id,
        status=status,
        created_at=now,
        updated_at=now,
    )


def _run(status, candidate_id, started_at=None):
    now = started_at or datetime.now(UTC)
    return SimpleNamespace(
        id=f"run-{candidate_id}",
        process_candidate_id=candidate_id,
        status=status,
        call_attempts=1,
        started_at=started_at,
        created_at=now,
        updated_at=now,
        twilio_status_detail=None,
        twilio_call_sid=None,
    )


def test_cv_processing_is_visible_as_detailed_stage_but_persisted_as_uploaded():
    progress = build_process_progress(
        _process(),
        [_candidate("CV_PROCESSING", "pc-1")],
        [],
        has_job_description=True,
    )

    assert progress.stage == "CV_PROCESSING"
    assert progress.process_status == "CVS_UPLOADED"
    assert progress.counts["cv_pending"] == 1
    assert progress.counts["cv_processing"] == 1


def test_loaded_cv_waits_for_manual_analysis_without_showing_active_processing():
    progress = build_process_progress(
        _process(),
        [_candidate("LOADED", "pc-1")],
        [],
        has_job_description=True,
    )

    assert progress.stage == "CVS_UPLOADED"
    assert progress.stage_label == "CVs cargados"
    assert progress.process_status == "CVS_UPLOADED"


def test_cv_error_is_visible_and_keeps_manual_retry_available():
    progress = build_process_progress(
        _process(),
        [_candidate("CV_ERROR", "pc-1")],
        [],
        has_job_description=True,
    )

    assert progress.stage == "CV_ERROR"
    assert progress.stage_label == "CVs con errores"
    assert progress.process_status == "CVS_UPLOADED"
    assert progress.counts["cv_errors"] == 1


def test_question_set_moves_matched_process_to_profiling_configured():
    assert (
        derive_process_stage(
            "MATCH_DONE",
            True,
            True,
            ["MATCHED"],
            [],
        )
        == "PROFILING_CONFIGURED"
    )


def test_match_pending_is_ready_for_match_but_not_currently_processing():
    progress = build_process_progress(
        _process(status="CVS_UPLOADED"),
        [_candidate("MATCH_PENDING", "pc-1")],
        [],
        has_job_description=True,
    )

    assert progress.stage == "CVS_PROCESSED"
    assert progress.stage_label == "CVs procesados"
    assert progress.process_status == "CVS_UPLOADED"
    assert progress.counts["match_pending"] == 1


def test_profiling_failure_is_terminal_and_process_can_complete():
    progress = build_process_progress(
        _process(status="PROFILING_ACTIVE", question_set_id="set-1"),
        [_candidate("PROFILING_FAILED", "pc-1")],
        [_run("FAILED", "pc-1")],
        has_job_description=True,
    )

    assert progress.stage == "PROFILING_COMPLETED"
    assert progress.counts["profiling_failed"] == 1
    assert progress.counts["profiling_active"] == 0


def test_active_call_exposes_elapsed_time_and_stale_flag():
    started_at = datetime.now(UTC) - timedelta(hours=1)
    progress = build_process_progress(
        _process(status="PROFILING_ACTIVE", question_set_id="set-1"),
        [_candidate("PROFILING_CALLING", "pc-1")],
        [_run("ANSWERED", "pc-1", started_at)],
        has_job_description=True,
    )

    call = progress.active_calls[0]
    assert call["status"] == "ANSWERED"
    assert call["elapsed_seconds"] >= 3600
    assert call["is_stale"] is True
    assert progress.counts["calls_active"] == 1


def test_closed_and_archived_are_never_overwritten_by_projection():
    for status in ("CLOSED", "ARCHIVED"):
        progress = build_process_progress(
            _process(status=status),
            [_candidate("MATCHED", "pc-1")],
            [],
            has_job_description=True,
        )
        assert progress.stage == status
        assert progress.process_status == status
