"""merge whatsapp_conversation y AIFeedback

Revision ID: d4a4444a2ab1
Revises: 093babcf6bb6, 963559a48ef6
Create Date: 2026-07-09 08:52:53.916098

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a4444a2ab1'
down_revision: Union[str, Sequence[str], None] = ('093babcf6bb6', '963559a48ef6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
