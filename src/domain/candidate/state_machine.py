from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import CandidateStatus

_TRANSITIONS: dict[CandidateStatus, set[CandidateStatus]] = {
    CandidateStatus.LOADED: {
        CandidateStatus.CV_PROCESSING,
    },
    CandidateStatus.CV_PROCESSING: {
        CandidateStatus.MATCH_PENDING,
        CandidateStatus.CV_ERROR,
    },
    CandidateStatus.CV_ERROR: {
        CandidateStatus.CV_PROCESSING,  # reintento
    },
    CandidateStatus.MATCH_PENDING: {
        CandidateStatus.MATCHED,
    },
    CandidateStatus.MATCHED: {
        CandidateStatus.SELECTED_FOR_PROFILING,
        CandidateStatus.DISCARDED,
        CandidateStatus.MATCH_PENDING,  # reprocesar si cambia el JD
    },
    CandidateStatus.SELECTED_FOR_PROFILING: {
        CandidateStatus.PROFILING_QUEUED,
        CandidateStatus.MATCHED,  # deseleccionar
    },
    CandidateStatus.PROFILING_QUEUED: {
        CandidateStatus.PROFILING_CALLING,
        CandidateStatus.SELECTED_FOR_PROFILING,  # cancelado de la cola
        CandidateStatus.PROFILING_FAILED,  # consentimiento de WhatsApp -> REJECTED en espera
    },
    CandidateStatus.PROFILING_CALLING: {
        CandidateStatus.PROFILING_COMPLETED,
        CandidateStatus.PROFILING_FAILED,
    },
    CandidateStatus.PROFILING_FAILED: {
        CandidateStatus.PROFILING_QUEUED,  # reintento
        CandidateStatus.DISCARDED,
    },
    CandidateStatus.PROFILING_COMPLETED: set(),  # terminal — override humano posible
    CandidateStatus.DISCARDED: {
        CandidateStatus.MATCHED,  # RB-008: el recruiter puede revertir
    },
}


class CandidateStateMachine:

    @staticmethod
    def transition(current: CandidateStatus, target: CandidateStatus) -> CandidateStatus:
        allowed = _TRANSITIONS.get(current, set())
        if target not in allowed:
            raise BusinessRuleException(
                f"Transicion invalida para candidato: {current.value} -> {target.value}. "
                f"Permitidas: {[s.value for s in allowed]}"
            )
        return target

    @staticmethod
    def can_be_ranked(status: CandidateStatus) -> bool:
        """RB-002: Solo candidatos con CV procesado pueden rankearse."""
        return status not in {
            CandidateStatus.LOADED,
            CandidateStatus.CV_PROCESSING,
            CandidateStatus.CV_ERROR,
        }

    @staticmethod
    def can_be_selected_for_profiling(status: CandidateStatus) -> bool:
        return status == CandidateStatus.MATCHED

    @staticmethod
    def is_discarded_automatically_blocked() -> bool:
        """RB-008: Un candidato nunca se descarta automáticamente."""
        return True
