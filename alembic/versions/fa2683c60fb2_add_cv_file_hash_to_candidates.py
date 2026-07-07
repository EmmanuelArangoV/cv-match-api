"""Add cv_file_hash to candidates

Revision ID: fa2683c60fb2
Revises: d535de29cfdd
Create Date: 2026-07-06 07:48:33.871273

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa2683c60fb2'
down_revision: Union[str, Sequence[str], None] = 'd535de29cfdd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('candidates', sa.Column('cv_file_hash', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_candidates_cv_file_hash'), 'candidates', ['cv_file_hash'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_candidates_cv_file_hash'), table_name='candidates')
    op.drop_column('candidates', 'cv_file_hash')
