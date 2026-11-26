"""Track the task that owns a CV analysis claim."""

import sqlalchemy as sa

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("process_candidates", sa.Column("cv_task_id", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("process_candidates", "cv_task_id")
