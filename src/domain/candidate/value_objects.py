from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date

from src.domain.shared.exceptions import BusinessRuleException
from src.domain.shared.value_objects import ValueObject


class AvailabilityType(str, enum.Enum):
    ANYTIME = "ANYTIME"
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    SPECIFIC_WINDOW = "SPECIFIC_WINDOW"


@dataclass(frozen=True)
class MatchScore(ValueObject):
    value: float

    def _validate(self) -> None:
        if not (0.0 <= self.value <= 100.0):
            raise BusinessRuleException(f"El match score debe estar entre 0 y 100, recibido: {self.value}")

    @property
    def category(self) -> str:
        if self.value >= 80:
            return "HIGH"
        if self.value >= 60:
            return "MEDIUM"
        if self.value >= 40:
            return "LOW"
        return "NOT_RECOMMENDED"

    def __str__(self) -> str:
        return f"{self.value:.1f}%"


@dataclass(frozen=True)
class AvailabilityPreference(ValueObject):
    type: AvailabilityType
    date: date | None = None
    start_time: str | None = None  # "HH:MM"
    end_time: str | None = None    # "HH:MM"

    def _validate(self) -> None:
        if self.type == AvailabilityType.SPECIFIC_WINDOW:
            if not self.date:
                raise BusinessRuleException("SPECIFIC_WINDOW requiere una fecha")
            if self.start_time and self.end_time:
                if self.start_time >= self.end_time:
                    raise BusinessRuleException("start_time debe ser anterior a end_time")

    def to_dict(self) -> dict:
        data: dict = {"preference": self.type.value}
        if self.date:
            data["date"] = self.date.isoformat()
        if self.start_time:
            data["start_time"] = self.start_time
        if self.end_time:
            data["end_time"] = self.end_time
        return data

    @classmethod
    def from_dict(cls, data: dict) -> AvailabilityPreference:
        availability_type = AvailabilityType(data["preference"])
        raw_date = data.get("date")
        return cls(
            type=availability_type,
            date=date.fromisoformat(raw_date) if raw_date else None,
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
        )

    @classmethod
    def anytime(cls) -> AvailabilityPreference:
        return cls(type=AvailabilityType.ANYTIME)
