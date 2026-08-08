"""add auditable cost tracking

Revision ID: f9b2c4d6e8a0
Revises: e2f47d9c6a10
Create Date: 2026-08-08 17:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f9b2c4d6e8a0"
down_revision: str | Sequence[str] | None = "e2f47d9c6a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cost_logs", sa.Column("provider", sa.String(length=50), nullable=True))
    op.add_column(
        "cost_logs", sa.Column("tokens_cached", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "cost_logs",
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="USD"
        ),
    )
    op.add_column(
        "cost_logs",
        sa.Column(
            "cost_source",
            sa.String(length=40),
            nullable=False,
            server_default="legacy_estimate",
        ),
    )
    op.add_column(
        "cost_logs", sa.Column("external_reference", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "cost_logs",
        sa.Column(
            "cost_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column(
        "cost_logs",
        "estimated_cost",
        existing_type=sa.Numeric(10, 6),
        type_=sa.Numeric(14, 9),
        existing_nullable=False,
    )
    op.create_unique_constraint(
        "uq_cost_logs_external_reference", "cost_logs", ["external_reference"]
    )

    # Identifica el proveedor de las filas históricas sin fingir que su cálculo fue exacto.
    op.execute(
        """
        UPDATE cost_logs
        SET provider = CASE
            WHEN operation_type IN ('CV_EXTRACTION','CV_MATCH','JD_ENHANCEMENT','ANSWER_EVALUATION')
                THEN 'OPENAI'
            WHEN operation_type = 'TWILIO_CALL' THEN 'TWILIO'
            WHEN operation_type = 'VOICE_CALL' THEN 'ELEVENLABS'
            WHEN operation_type = 'WHATSAPP_MESSAGE' THEN 'META'
            ELSE provider
        END
        WHERE provider IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("uq_cost_logs_external_reference", "cost_logs", type_="unique")
    op.alter_column(
        "cost_logs",
        "estimated_cost",
        existing_type=sa.Numeric(14, 9),
        type_=sa.Numeric(10, 6),
        existing_nullable=False,
    )
    op.drop_column("cost_logs", "cost_breakdown")
    op.drop_column("cost_logs", "external_reference")
    op.drop_column("cost_logs", "cost_source")
    op.drop_column("cost_logs", "currency")
    op.drop_column("cost_logs", "tokens_cached")
    op.drop_column("cost_logs", "provider")
