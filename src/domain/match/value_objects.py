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
