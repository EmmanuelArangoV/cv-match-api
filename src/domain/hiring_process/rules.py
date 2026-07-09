"""
Reglas de negocio del dominio HiringProcess.
Cada método corresponde a una o más reglas del PRD (RB-001 a RB-010).
"""

from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import ProcessStatus, WhatsAppConsentStatus


class HiringProcessRules:
    @staticmethod
    def require_job_description(has_jd: bool) -> None:
        """RB-001: No se puede ejecutar match sin Job Description."""
        if not has_jd:
            raise BusinessRuleException(
                "El proceso no tiene un Job Description activo. "
                "Carga o crea el JD antes de ejecutar el match."
            )

    @staticmethod
    def require_question_set_for_profiling(question_set_id: object) -> None:
        """RB-003: El botón de profiling solo se habilita con set de preguntas asignado."""
        if not question_set_id:
            raise BusinessRuleException(
                "El proceso no tiene un set de preguntas asignado. "
                "Asocia un set antes de activar el profiling."
            )

    @staticmethod
    def require_manual_candidate_selection(candidate_ids: list) -> None:
        """RB-004: No se pueden iniciar llamadas sin selección manual del usuario."""
        if not candidate_ids:
            raise BusinessRuleException(
                "Debes seleccionar al menos un candidato para iniciar el profiling."
            )

    @staticmethod
    def enforce_max_concurrent_calls(active_calls: int, max_calls: int) -> None:
        """RB-005: La concurrencia máxima de llamadas activas es configurable (default 4)."""
        if active_calls >= max_calls:
            raise BusinessRuleException(
                f"Se alcanzó el límite de {max_calls} llamadas simultáneas. "
                "Los candidatos restantes quedan en cola."
            )

    @staticmethod
    def require_active_process(status: ProcessStatus) -> None:
        """Un proceso cerrado o archivado no permite operaciones."""
        if status in {ProcessStatus.CLOSED, ProcessStatus.ARCHIVED}:
            raise BusinessRuleException(
                f"El proceso está {status.value} y no permite modificaciones."
            )

    @staticmethod
    def require_budget_available(spent_usd: float, budget_max_usd: float) -> None:
        """RB-010: Si el costo supera el presupuesto, bloquear nuevas ejecuciones."""
        if budget_max_usd > 0 and spent_usd >= budget_max_usd:
            raise BusinessRuleException(
                f"El proceso ha alcanzado su presupuesto máximo de ${budget_max_usd:.2f} USD. "
                "Solicita aprobación para continuar."
            )

    @staticmethod
    def can_candidate_be_called(whatsapp_status: WhatsAppConsentStatus) -> tuple[bool, bool]:
        """
        Determina si un candidato puede ser contactado por llamada.
        Retorna (puede_llamar, requiere_consentimiento_en_llamada).

        - ACCEPTED   → puede llamar, consentimiento ya dado
        - TIMEOUT    → puede llamar en frío, el bot debe pedir consentimiento
        - PENDING    → puede llamar en frío (aún no se ha enviado o respondido WA)
        - REJECTED   → NO se puede llamar, marcar alerta
        """
        if whatsapp_status == WhatsAppConsentStatus.REJECTED:
            return False, False
        if whatsapp_status == WhatsAppConsentStatus.ACCEPTED:
            return True, False
        # TIMEOUT o PENDING → llamada en frío
        return True, True

    @staticmethod
    def require_cv_processed(cv_status: str) -> None:
        """RB-002: Un CV no puede ser rankeado si no fue procesado correctamente."""
        if cv_status in {"LOADED", "CV_PROCESSING", "CV_ERROR"}:
            raise BusinessRuleException(
                "El CV aún no ha sido procesado correctamente y no puede ser rankeado."
            )
