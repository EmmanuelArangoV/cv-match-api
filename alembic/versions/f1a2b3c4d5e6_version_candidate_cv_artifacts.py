"""version candidate CV artifacts per application

Revision ID: f1a2b3c4d5e6
Revises: e9a1b2c3d4f5
Create Date: 2026-09-08 12:00:00
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e9a1b2c3d4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_cv_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_file_url", sa.TEXT(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("normalized_file_url", sa.TEXT(), nullable=True),
        sa.Column("extracted_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("normalized_cv", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cv_embedding", Vector(dim=1536), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_candidate_cv_versions_candidate_id",
        "candidate_cv_versions",
        ["candidate_id"],
    )
    op.create_index(
        "ix_candidate_cv_versions_file_hash",
        "candidate_cv_versions",
        ["file_hash"],
    )
    op.add_column(
        "process_candidates",
        sa.Column("cv_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Backfill exacto: cada Candidate conserva una versión inicial con su snapshot
    # heredado, y todas las postulaciones existentes apuntan a esa misma versión.
    # No elimina ni modifica las columnas antiguas de candidates.
    connection = op.get_bind()
    candidate_ids = connection.execute(sa.text("SELECT id FROM candidates")).scalars().all()
    for candidate_id in candidate_ids:
        version_id = uuid.uuid4()
        connection.execute(
            sa.text(
                """
                INSERT INTO candidate_cv_versions (
                    id,
                    candidate_id,
                    original_file_url,
                    file_hash,
                    normalized_file_url,
                    extracted_profile,
                    normalized_cv,
                    cv_embedding
                )
                SELECT
                    :version_id,
                    id,
                    cv_file_url,
                    cv_file_hash,
                    normalized_cv_url,
                    extracted_profile,
                    normalized_cv,
                    cv_embedding
                FROM candidates
                WHERE id = :candidate_id
                """
            ),
            {"version_id": version_id, "candidate_id": candidate_id},
        )
        connection.execute(
            sa.text(
                """
                UPDATE process_candidates
                SET cv_version_id = :version_id
                WHERE candidate_id = :candidate_id
                """
            ),
            {"version_id": version_id, "candidate_id": candidate_id},
        )

    # La guardia cubre una base sin candidatos previos y deja explícito que cada
    # postulación debe resolver una versión antes de imponer NOT NULL.
    connection.execute(
        sa.text(
            """
            UPDATE process_candidates
            SET cv_version_id = versions.id
            FROM candidate_cv_versions AS versions
            WHERE process_candidates.cv_version_id IS NULL
              AND process_candidates.candidate_id = versions.candidate_id
            """
        )
    )

    op.create_foreign_key(
        "fk_process_candidates_cv_version_id",
        "process_candidates",
        "candidate_cv_versions",
        ["cv_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_process_candidates_cv_version_id",
        "process_candidates",
        ["cv_version_id"],
    )
    op.alter_column("process_candidates", "cv_version_id", nullable=False)


def downgrade() -> None:
    op.drop_index("ix_process_candidates_cv_version_id", table_name="process_candidates")
    op.drop_constraint(
        "fk_process_candidates_cv_version_id",
        "process_candidates",
        type_="foreignkey",
    )
    op.drop_column("process_candidates", "cv_version_id")
    op.drop_index("ix_candidate_cv_versions_file_hash", table_name="candidate_cv_versions")
    op.drop_index("ix_candidate_cv_versions_candidate_id", table_name="candidate_cv_versions")
    op.drop_table("candidate_cv_versions")
