"""Maquina de estados tecnica de una corrida de profiling."""

from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import ProfilingRunStatus

ACTIVE_PROFILING_RUN_STATUSES = frozenset(
    {
        ProfilingRunStatus.PENDING,
        ProfilingRunStatus.QUEUED,
        ProfilingRunStatus.CALLING,
        ProfilingRunStatus.ANSWERED,
        ProfilingRunStatus.RETRY_PENDING,
    }
)

TERMINAL_PROFILING_RUN_STATUSES = frozenset(
    {
        ProfilingRunStatus.COMPLETED,
        ProfilingRunStatus.FAILED,
        ProfilingRunStatus.NO_ANSWER,
        ProfilingRunStatus.VOICEMAIL_DETECTED,
        ProfilingRunStatus.CANCELLED,
    }
)

_TRANSITIONS: dict[ProfilingRunStatus, set[ProfilingRunStatus]] = {
    ProfilingRunStatus.PENDING: {
        ProfilingRunStatus.QUEUED,
        ProfilingRunStatus.CANCELLED,
        ProfilingRunStatus.FAILED,
    },
    ProfilingRunStatus.QUEUED: {
        ProfilingRunStatus.CALLING,
        ProfilingRunStatus.CANCELLED,
        ProfilingRunStatus.FAILED,
    },
    ProfilingRunStatus.CALLING: {
        ProfilingRunStatus.ANSWERED,
        ProfilingRunStatus.RETRY_PENDING,
        ProfilingRunStatus.NO_ANSWER,
        ProfilingRunStatus.VOICEMAIL_DETECTED,
        ProfilingRunStatus.FAILED,
    },
    ProfilingRunStatus.ANSWERED: {
        ProfilingRunStatus.COMPLETED,
        ProfilingRunStatus.FAILED,
    },
    ProfilingRunStatus.RETRY_PENDING: {
        ProfilingRunStatus.QUEUED,
        ProfilingRunStatus.CANCELLED,
        ProfilingRunStatus.FAILED,
    },
    ProfilingRunStatus.COMPLETED: set(),
    ProfilingRunStatus.FAILED: set(),
    ProfilingRunStatus.NO_ANSWER: set(),
    ProfilingRunStatus.VOICEMAIL_DETECTED: set(),
    ProfilingRunStatus.CANCELLED: set(),
}


class ProfilingRunStateMachine:
    @staticmethod
    def transition(current: ProfilingRunStatus, target: ProfilingRunStatus) -> ProfilingRunStatus:
        allowed = _TRANSITIONS.get(current, set())
        if target not in allowed:
            raise BusinessRuleException(
                f"Transicion invalida para corrida de profiling: "
                f"{current.value} -> {target.value}. "
                f"Permitidas: {[status.value for status in allowed]}"
            )
        return target

    @staticmethod
    def is_active(status: ProfilingRunStatus) -> bool:
        return status in ACTIVE_PROFILING_RUN_STATUSES

    @staticmethod
    def is_terminal(status: ProfilingRunStatus) -> bool:
        return status in TERMINAL_PROFILING_RUN_STATUSES
