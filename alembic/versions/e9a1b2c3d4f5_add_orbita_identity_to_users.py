"""add Orbita identity to users

Revision ID: e9a1b2c3d4f5
Revises: d8f2a4c6e9b1
Create Date: 2026-09-02 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e9a1b2c3d4f5"
down_revision: str | Sequence[str] | None = "d8f2a4c6e9b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.add_column(
        "users",
        sa.Column("orbita_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_users_orbita_user_id",
        "users",
        ["orbita_user_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_orbita_user_id", "users", type_="unique")
    op.drop_column("users", "orbita_user_id")
    # Mantiene las cuentas creadas por SSO inutilizables por contraseña tras un downgrade.
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )
