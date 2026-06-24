from __future__ import annotations

import enum
from dataclasses import dataclass

from src.domain.shared.value_objects import ValueObject


class AdvancementLevel(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class AdvancementProbability(ValueObject):
    level: AdvancementLevel
    explanation: str
    requires_human_review: bool = False

    @property
    def descriptor(self) -> str:
        descriptors = {
            AdvancementLevel.HIGH: "Recomendado para avanzar a revisión humana o siguiente etapa",
            AdvancementLevel.MEDIUM: "Puede avanzar, pero requiere validación puntual antes de continuar",
            AdvancementLevel.LOW: "No se recomienda avanzar sin revisión explícita de TA",
        }
        return descriptors[self.level]

    @classmethod
    def from_scores(
        cls,
        critical_questions_passed: bool,
        failed_critical_count: int,
        total_weighted_score: float,
        low_confidence_transcription: bool,
        explanation: str,
    ) -> AdvancementProbability:
        """
        Calcula la posibilidad de avance según las reglas del negocio (RB-006, RB-007).
        - RB-006: preguntas críticas incumplidas → mínimo MEDIUM
        - RB-007: respuesta crítica incorrecta → puede bajar a LOW
        """
        requires_review = low_confidence_transcription

        if not critical_questions_passed or failed_critical_count >= 2:
            return cls(
                level=AdvancementLevel.LOW,
                explanation=explanation,
                requires_human_review=True,
            )

        if failed_critical_count == 1 or total_weighted_score < 50:
            return cls(
                level=AdvancementLevel.MEDIUM,
                explanation=explanation,
                requires_human_review=requires_review,
            )

        return cls(
            level=AdvancementLevel.HIGH,
            explanation=explanation,
            requires_human_review=requires_review,
        )
