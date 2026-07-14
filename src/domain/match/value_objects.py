from __future__ import annotations

from dataclasses import dataclass

from src.domain.shared.exceptions import BusinessRuleException
from src.domain.shared.value_objects import ValueObject

_DEFAULT_WEIGHTS = {
    "technical_skills": 45,
    "relevant_experience": 25,
    "seniority": 15,
    "industry_domain": 7,
    "languages": 5,
    "education_certifications": 3,
}


@dataclass(frozen=True)
class MatchWeights(ValueObject):
    technical_skills: int = 45
    relevant_experience: int = 25
    seniority: int = 15
    industry_domain: int = 7
    languages: int = 5
    education_certifications: int = 3

    def _validate(self) -> None:
        total = (
            self.technical_skills
            + self.relevant_experience
            + self.seniority
            + self.industry_domain
            + self.languages
            + self.education_certifications
        )
        if total != 100:
            raise BusinessRuleException(f"Los pesos del match deben sumar 100, suman: {total}")

        for field_name, value in self.to_dict().items():
            if value < 0:
                raise BusinessRuleException(f"El peso '{field_name}' no puede ser negativo")

    def to_dict(self) -> dict:
        return {
            "technical_skills": self.technical_skills,
            "relevant_experience": self.relevant_experience,
            "seniority": self.seniority,
            "industry_domain": self.industry_domain,
            "languages": self.languages,
            "education_certifications": self.education_certifications,
        }

    @classmethod
    def default(cls) -> MatchWeights:
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> MatchWeights:
        merged = {**_DEFAULT_WEIGHTS, **data}
        return cls(**merged)


_DEFAULT_THRESHOLDS = {"high": 75, "medium": 50, "low": 30}


@dataclass(frozen=True)
class MatchThresholds(ValueObject):
    high: int = 75
    medium: int = 50
    low: int = 30

    def _validate(self) -> None:
        if not (0 <= self.low <= self.medium <= self.high <= 100):
            raise BusinessRuleException(
                "Los umbrales de match deben cumplir 0 <= low <= medium <= high <= 100, "
                f"recibido: low={self.low}, medium={self.medium}, high={self.high}"
            )

    def to_dict(self) -> dict:
        return {"high": self.high, "medium": self.medium, "low": self.low}

    def category_for(self, overall_score: float) -> str:
        if overall_score >= self.high:
            return "HIGH"
        if overall_score >= self.medium:
            return "MEDIUM"
        if overall_score >= self.low:
            return "LOW"
        return "NOT_RECOMMENDED"

    @classmethod
    def default(cls) -> MatchThresholds:
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> MatchThresholds:
        merged = {**_DEFAULT_THRESHOLDS, **data}
        return cls(**merged)
