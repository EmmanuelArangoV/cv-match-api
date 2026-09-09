"""merge Orbita SSO and bilingual CV heads

Revision ID: f3c4d5e6f70
Revises: f0c8d2a7e5b1, f2b3c4d5e6f7
Create Date: 2026-09-09 08:00:00
"""

from collections.abc import Sequence

revision: str = "f3c4d5e6f70"
down_revision: str | Sequence[str] | None = ("f0c8d2a7e5b1", "f2b3c4d5e6f7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
