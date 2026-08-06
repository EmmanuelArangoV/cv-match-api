from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import ProcessStatus

# Transiciones válidas: estado_actual → set de estados destino permitidos
# ARCHIVED se permite directamente desde cualquier estado no terminal (además de desde CLOSED):
# "Archivar proceso" es una acción administrativa que no exige pasar primero por "Cerrar".
_TRANSITIONS: dict[ProcessStatus, set[ProcessStatus]] = {
    ProcessStatus.DRAFT: {
        ProcessStatus.CVS_UPLOADED,
        ProcessStatus.CLOSED,
        ProcessStatus.ARCHIVED,
    },
    ProcessStatus.CVS_UPLOADED: {
        ProcessStatus.MATCH_PROCESSING,
        ProcessStatus.CVS_UPLOADED,  # cargar más CVs
        ProcessStatus.CLOSED,
        ProcessStatus.ARCHIVED,
    },
    ProcessStatus.MATCH_PROCESSING: {
        ProcessStatus.MATCH_DONE,
        ProcessStatus.CLOSED,
        ProcessStatus.ARCHIVED,
    },
    ProcessStatus.MATCH_DONE: {
        ProcessStatus.PROFILING_CONFIGURED,
        ProcessStatus.MATCH_PROCESSING,  # reprocesar con nuevo JD
        ProcessStatus.CVS_UPLOADED,  # cargar más CVs
        ProcessStatus.CLOSED,
        ProcessStatus.ARCHIVED,
    },
    ProcessStatus.PROFILING_CONFIGURED: {
        ProcessStatus.PROFILING_ACTIVE,
        ProcessStatus.MATCH_PROCESSING,  # cambió el JD
        ProcessStatus.CVS_UPLOADED,  # cargar más CVs
        ProcessStatus.CLOSED,
        ProcessStatus.ARCHIVED,
    },
    ProcessStatus.PROFILING_ACTIVE: {
        ProcessStatus.PROFILING_COMPLETED,
        ProcessStatus.PROFILING_CONFIGURED,  # se canceló el profiling
        ProcessStatus.CLOSED,
        ProcessStatus.ARCHIVED,
    },
    ProcessStatus.PROFILING_COMPLETED: {
        ProcessStatus.CLOSED,
        ProcessStatus.PROFILING_ACTIVE,  # iniciar profiling adicional
        ProcessStatus.ARCHIVED,
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
