from __future__ import annotations

from datetime import datetime, timedelta

from src.infrastructure.db.models import ProfilingRunStatus

WATCHED_STATUSES = (ProfilingRunStatus.CALLING.value, ProfilingRunStatus.ANSWERED.value)


def stale_reference_at(started_at: datetime | None, created_at: datetime | None) -> datetime | None:
    """Momento desde el que una llamada activa debe expirar.

    Las corridas creadas antes de centralizar el lifecycle pueden estar en
    ``CALLING`` sin ``started_at``. ``created_at`` es una referencia conservadora: nunca acorta
    el timeout de una llamada nueva y evita que un registro histórico quede activo para siempre.
    """
    return started_at or created_at


def is_run_stale(
    status: str,
    started_at: datetime | None,
    now: datetime,
    calling_timeout_seconds: int,
    answered_timeout_seconds: int,
    *,
    created_at: datetime | None = None,
) -> bool:
    """
    Un ProfilingRun queda atascado cuando nunca llega el webhook que deberia
    cerrarlo: CALLING (nunca llego el status callback de Twilio) o ANSWERED
    (un humano contesto pero nunca llego el post-call nativo de ElevenLabs,
    p.ej. porque colgo durante el aire muerto antes de que el agente conectara).
    """
    reference_at = stale_reference_at(started_at, created_at)
    if status not in WATCHED_STATUSES or reference_at is None:
        return False
    is_calling = status == ProfilingRunStatus.CALLING.value
    timeout_seconds = calling_timeout_seconds if is_calling else answered_timeout_seconds
    return reference_at < now - timedelta(seconds=timeout_seconds)
