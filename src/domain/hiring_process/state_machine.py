from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import ProcessStatus

# Transiciones válidas: estado_actual → set de estados destino permitidos
_TRANSITIONS: dict[ProcessStatus, set[ProcessStatus]] = {
    ProcessStatus.DRAFT: {
        ProcessStatus.CVS_UPLOADED,
    },
    ProcessStatus.CVS_UPLOADED: {
        ProcessStatus.MATCH_PROCESSING,
        ProcessStatus.CVS_UPLOADED,  # cargar más CVs
        ProcessStatus.CLOSED,
    },
    ProcessStatus.MATCH_PROCESSING: {
        ProcessStatus.MATCH_DONE,
    },
    ProcessStatus.MATCH_DONE: {
        ProcessStatus.PROFILING_CONFIGURED,
        ProcessStatus.MATCH_PROCESSING,  # reprocesar con nuevo JD
        ProcessStatus.CVS_UPLOADED,      # cargar más CVs
        ProcessStatus.CLOSED,
    },
    ProcessStatus.PROFILING_CONFIGURED: {
        ProcessStatus.PROFILING_ACTIVE,
        ProcessStatus.MATCH_PROCESSING,  # cambió el JD
        ProcessStatus.CVS_UPLOADED,      # cargar más CVs
        ProcessStatus.CLOSED,
    },
    ProcessStatus.PROFILING_ACTIVE: {
        ProcessStatus.PROFILING_COMPLETED,
        ProcessStatus.PROFILING_CONFIGURED,  # se canceló el profiling
    },
    ProcessStatus.PROFILING_COMPLETED: {
        ProcessStatus.CLOSED,
        ProcessStatus.PROFILING_ACTIVE,  # iniciar profiling adicional
    },
    ProcessStatus.CLOSED: {
        ProcessStatus.ARCHIVED,
    },
    ProcessStatus.ARCHIVED: set(),  # estado terminal
}


class HiringProcessStateMachine:

    @staticmethod
    def transition(current: ProcessStatus, target: ProcessStatus) -> ProcessStatus:
        allowed = _TRANSITIONS.get(current, set())
        if target not in allowed:
            raise BusinessRuleException(
                f"Transicion invalida: {current.value} -> {target.value}. "
                f"Permitidas: {[s.value for s in allowed]}"
            )
        return target

    @staticmethod
    def can_upload_cvs(status: ProcessStatus) -> bool:
        return status in {
            ProcessStatus.DRAFT,
            ProcessStatus.CVS_UPLOADED,
            ProcessStatus.MATCH_DONE,
            ProcessStatus.PROFILING_CONFIGURED,
        }

    @staticmethod
    def can_run_match(status: ProcessStatus) -> bool:
        return status in {
            ProcessStatus.CVS_UPLOADED,
            ProcessStatus.MATCH_DONE,
            ProcessStatus.PROFILING_CONFIGURED,
        }

    @staticmethod
    def can_start_profiling(status: ProcessStatus) -> bool:
        return status == ProcessStatus.PROFILING_CONFIGURED

    @staticmethod
    def is_active(status: ProcessStatus) -> bool:
        return status not in {ProcessStatus.CLOSED, ProcessStatus.ARCHIVED}
