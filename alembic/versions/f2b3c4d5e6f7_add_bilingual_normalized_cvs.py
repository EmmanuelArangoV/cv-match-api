"""store bilingual normalized CV artifacts and translation defaults

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-09-08 15:30:00
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "f2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRANSLATION_PROMPT_ID = UUID("f20e9f17-bb14-4c11-a8e1-8b1c6f0d4001")
_TRANSLATION_MODEL_ID = UUID("f20e9f17-bb14-4c11-a8e1-8b1c6f0d4002")
_TRANSLATION_PROMPT = """You translate a normalized CV JSON into the requested target language.

Return ONLY one valid JSON object. Preserve the exact schema, keys, arrays, facts, dates,
names, institutions, credentials and identifiers. Translate only human-readable values. Never
translate technology, product, framework, library, programming-language, certification or company
names. Do not infer, add, remove or redact data: rendering redacts contact data separately."""


def upgrade() -> None:
    op.add_column("candidate_cv_versions", sa.Column("normalized_file_url_es", sa.TEXT()))
    op.add_column("candidate_cv_versions", sa.Column("normalized_file_url_en", sa.TEXT()))
    op.execute(
        """
        UPDATE candidate_cv_versions
        SET normalized_file_url_es = normalized_file_url
        WHERE normalized_file_url_es IS NULL
        """
    )

    op.execute(
        sa.text(
            """
            INSERT INTO ai_prompts (id, task_type, version_name, system_prompt_text, is_active)
            SELECT :id, 'CV_TRANSLATION', 'v1-inicial', :prompt, true
            WHERE NOT EXISTS (
                SELECT 1 FROM ai_prompts
                WHERE task_type = 'CV_TRANSLATION' AND is_active
            )
            """
        ).bindparams(id=_TRANSLATION_PROMPT_ID, prompt=_TRANSLATION_PROMPT)
    )

    op.execute(
        sa.text(
            """
            INSERT INTO ai_model_configurations (id, task_type, provider, model_name, is_active)
            SELECT :id, 'CV_TRANSLATION', 'OPENAI', 'gpt-5.6-luna', true
            WHERE NOT EXISTS (
                SELECT 1 FROM ai_model_configurations
                WHERE task_type = 'CV_TRANSLATION' AND provider = 'OPENAI' AND is_active
            )
            """
        ).bindparams(id=_TRANSLATION_MODEL_ID)
    )


def downgrade() -> None:
    # Solo elimina los defaults inyectados por esta revisión; nunca una versión
    # creada por Admin posteriormente.
    op.execute(
        sa.text("DELETE FROM ai_model_configurations WHERE id = :id").bindparams(
            id=_TRANSLATION_MODEL_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM ai_prompts WHERE id = :id").bindparams(id=_TRANSLATION_PROMPT_ID)
    )
    op.drop_column("candidate_cv_versions", "normalized_file_url_en")
    op.drop_column("candidate_cv_versions", "normalized_file_url_es")
