from __future__ import annotations

from datetime import datetime, timedelta

from src.infrastructure.db.models import ProfilingRunStatus

WATCHED_STATUSES = (ProfilingRunStatus.CALLING.value, ProfilingRunStatus.ANSWERED.value)


def is_run_stale(
    status: str,
    started_at: datetime | None,
    now: datetime,
    calling_timeout_seconds: int,
    answered_timeout_seconds: int,
) -> bool:
    """
    Un ProfilingRun queda atascado cuando nunca llega el webhook que deberia
    cerrarlo: CALLING (nunca llego el status callback de Twilio) o ANSWERED
    (un humano contesto pero nunca llego el post-call nativo de ElevenLabs,
    p.ej. porque colgo durante el aire muerto antes de que el agente conectara).
    """
    if status not in WATCHED_STATUSES or started_at is None:
        return False
    is_calling = status == ProfilingRunStatus.CALLING.value
    timeout_seconds = calling_timeout_seconds if is_calling else answered_timeout_seconds
    return started_at < now - timedelta(seconds=timeout_seconds)
