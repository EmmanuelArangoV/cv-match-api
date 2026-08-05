"""add profiling run active and latest indexes

Revision ID: c4e7f2a91d30
Revises: 8f6d2a1c4b7e
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e7f2a91d30"
down_revision: str | Sequence[str] | None = "8f6d2a1c4b7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_profiling_runs_candidate_latest",
        "profiling_runs",
        ["process_candidate_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_profiling_runs_active_candidate",
        "profiling_runs",
        ["process_candidate_id"],
        unique=True,
        postgresql_where=(
            "status IN ('PENDING', 'QUEUED', 'CALLING', 'ANSWERED', 'RETRY_PENDING')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_profiling_runs_active_candidate", table_name="profiling_runs")
    op.drop_index("ix_profiling_runs_candidate_latest", table_name="profiling_runs")
