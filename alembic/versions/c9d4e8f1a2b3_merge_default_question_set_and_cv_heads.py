"""merge default question set and candidate CV migration heads.

Revision ID: c9d4e8f1a2b3
Revises: f0c8d2a7e5b1, f1a2b3c4d5e6
Create Date: 2026-09-08 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "c9d4e8f1a2b3"
down_revision: str | Sequence[str] | None = ("f0c8d2a7e5b1", "f1a2b3c4d5e6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Une las dos ramas de migración sin cambios adicionales de esquema."""


def downgrade() -> None:
    """La separación de ramas no requiere cambios de esquema."""
