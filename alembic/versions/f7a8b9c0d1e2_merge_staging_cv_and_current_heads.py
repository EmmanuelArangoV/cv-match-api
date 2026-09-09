"""merge the historical staging CV head with the current migration chain.

Revision ID: f7a8b9c0d1e2
Revises: c9d4e8f1a2b3, f6e7f809a1b2
Create Date: 2026-09-09 16:40:00.000000
"""

from collections.abc import Sequence


revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = ("c9d4e8f1a2b3", "f6e7f809a1b2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Conecta el estado de staging sin alterar el esquema ni los datos."""


def downgrade() -> None:
    """La separación de ramas no requiere cambios de esquema."""
