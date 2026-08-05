"""add recruiter analysis context to process candidates

Revision ID: 8f6d2a1c4b7e
Revises: 3746cb54ad07
Create Date: 2026-08-04 17:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8f6d2a1c4b7e"
down_revision: Union[str, Sequence[str], None] = "3746cb54ad07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "process_candidates",
        sa.Column("analysis_context", sa.TEXT(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("process_candidates", "analysis_context")
