"""version voice greeting with prompt revisions

Revision ID: c7a9e1f4b2d8
Revises: b4d8e2c1f6a3
Create Date: 2026-08-09 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7a9e1f4b2d8"
down_revision: str | Sequence[str] | None = "b4d8e2c1f6a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_prompts", sa.Column("first_message_text", sa.TEXT(), nullable=True))
    op.add_column(
        "process_ai_prompts", sa.Column("first_message_text", sa.TEXT(), nullable=True)
    )
    # Solo la revision activa puede representar con certeza el saludo vigente.
    # Las versiones historicas quedan en NULL en vez de inventar un valor retroactivo.
    op.execute(
        sa.text(
            """
            UPDATE process_ai_prompts AS prompt
            SET first_message_text = process.voice_override_first_message
            FROM hiring_processes AS process
            WHERE prompt.process_id = process.id
              AND prompt.task_type = 'VOICE_CALL_AGENT'
              AND prompt.is_active = true
              AND process.voice_override_first_message IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("process_ai_prompts", "first_message_text")
    op.drop_column("ai_prompts", "first_message_text")
