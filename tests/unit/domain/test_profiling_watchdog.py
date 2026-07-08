from datetime import UTC, datetime, timedelta

from src.domain.profiling.watchdog import is_run_stale
from src.infrastructure.db.models import ProfilingRunStatus

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
CALLING_TIMEOUT = 60
ANSWERED_TIMEOUT = 900


def test_calling_stale_past_timeout():
    started_at = NOW - timedelta(seconds=CALLING_TIMEOUT + 1)
    assert is_run_stale(
        ProfilingRunStatus.CALLING.value, started_at, NOW, CALLING_TIMEOUT, ANSWERED_TIMEOUT
    )


def test_calling_not_stale_within_timeout():
    started_at = NOW - timedelta(seconds=CALLING_TIMEOUT - 1)
    assert not is_run_stale(
        ProfilingRunStatus.CALLING.value, started_at, NOW, CALLING_TIMEOUT, ANSWERED_TIMEOUT
    )


def test_answered_stale_past_timeout():
    started_at = NOW - timedelta(seconds=ANSWERED_TIMEOUT + 1)
    assert is_run_stale(
        ProfilingRunStatus.ANSWERED.value, started_at, NOW, CALLING_TIMEOUT, ANSWERED_TIMEOUT
    )


def test_answered_not_stale_within_timeout():
    started_at = NOW - timedelta(seconds=ANSWERED_TIMEOUT - 1)
    assert not is_run_stale(
        ProfilingRunStatus.ANSWERED.value, started_at, NOW, CALLING_TIMEOUT, ANSWERED_TIMEOUT
    )


def test_answered_timeout_does_not_apply_to_calling_status():
    # started_at cruza el umbral de ANSWERED pero no el de CALLING (mas corto)
    started_at = NOW - timedelta(seconds=ANSWERED_TIMEOUT + 1)
    assert is_run_stale(
        ProfilingRunStatus.CALLING.value, started_at, NOW, CALLING_TIMEOUT, ANSWERED_TIMEOUT
    )


def test_completed_status_never_stale():
    started_at = NOW - timedelta(days=1)
    assert not is_run_stale(
        ProfilingRunStatus.COMPLETED.value, started_at, NOW, CALLING_TIMEOUT, ANSWERED_TIMEOUT
    )


def test_voicemail_detected_status_never_stale():
    started_at = NOW - timedelta(days=1)
    assert not is_run_stale(
        ProfilingRunStatus.VOICEMAIL_DETECTED.value,
        started_at,
        NOW,
        CALLING_TIMEOUT,
        ANSWERED_TIMEOUT,
    )


def test_none_started_at_never_stale():
    assert not is_run_stale(
        ProfilingRunStatus.CALLING.value, None, NOW, CALLING_TIMEOUT, ANSWERED_TIMEOUT
    )
