from dataclasses import dataclass


@dataclass(frozen=True)
class ValueObject:
    """Base para todos los value objects — inmutables y con validación en creación."""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        pass
