"""ensure whatsapp conversation column

Revision ID: e2f47d9c6a10
Revises: c4e7f2a91d30
Create Date: 2026-08-08 12:45:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2f47d9c6a10"
down_revision: str | Sequence[str] | None = "c4e7f2a91d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Repair databases where the old parallel migration dropped the column."""
    op.execute(
        sa.text(
            "ALTER TABLE process_candidates ADD COLUMN IF NOT EXISTS whatsapp_conversation JSONB"
        )
    )


def downgrade() -> None:
    """Keep the shared column because revision 093babcf6bb6 owns it."""
