"""upgrade standard process voice prompts

Revision ID: f6e7f809a1b2
Revises: f5d6e7f809a1
Create Date: 2026-09-09 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6e7f809a1b2"
down_revision: str | Sequence[str] | None = "f5d6e7f809a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VOICE_PROMPT_V2_ID = "56000000-0000-4000-8000-000000000006"
_VOICE_PROMPT_V3_ID = "56000000-0000-4000-8000-000000000007"
_VOICE_PROMPT_V4_ID = "56000000-0000-4000-8000-000000000008"
_MIGRATED_VERSION = "v4-conversacion-calida · migrada"


def upgrade() -> None:
    """Versiona las copias estándar sin alterar prompts propios de cada proceso."""
    op.execute(
        sa.text(
            """
            WITH template AS (
                SELECT id, system_prompt_text, first_message_text
                FROM ai_prompts
                WHERE id = CAST(:template_id AS uuid)
                  AND task_type = 'VOICE_CALL_AGENT'
            ),
            deactivated AS (
                UPDATE process_ai_prompts AS prompt
                SET is_active = false
                WHERE prompt.task_type = 'VOICE_CALL_AGENT'
                  AND prompt.is_active = true
                  AND prompt.source_prompt_id IN (
                      CAST(:v2_id AS uuid), CAST(:v3_id AS uuid)
                  )
                  AND EXISTS (SELECT 1 FROM template)
                RETURNING prompt.id, prompt.process_id, prompt.created_by
            )
            INSERT INTO process_ai_prompts (
                id, process_id, task_type, version_name, system_prompt_text,
                first_message_text, source_prompt_id, is_active, created_by
            )
            SELECT
                CAST(
                    substr(md5('v4-conversacion-calida:' || previous.id::text), 1, 8) || '-' ||
                    substr(md5('v4-conversacion-calida:' || previous.id::text), 9, 4) || '-' ||
                    substr(md5('v4-conversacion-calida:' || previous.id::text), 13, 4) || '-' ||
                    substr(md5('v4-conversacion-calida:' || previous.id::text), 17, 4) || '-' ||
                    substr(md5('v4-conversacion-calida:' || previous.id::text), 21, 12)
                    AS uuid
                ),
                previous.process_id,
                'VOICE_CALL_AGENT',
                :version_name,
                template.system_prompt_text,
                template.first_message_text,
                template.id,
                true,
                previous.created_by
            FROM deactivated AS previous
            CROSS JOIN template
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            template_id=_VOICE_PROMPT_V4_ID,
            v2_id=_VOICE_PROMPT_V2_ID,
            v3_id=_VOICE_PROMPT_V3_ID,
            version_name=_MIGRATED_VERSION,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE process_ai_prompts
            SET is_active = false
            WHERE task_type = 'VOICE_CALL_AGENT'
              AND source_prompt_id = CAST(:template_id AS uuid)
              AND version_name = :version_name
              AND is_active = true
            """
        ).bindparams(template_id=_VOICE_PROMPT_V4_ID, version_name=_MIGRATED_VERSION)
    )
    op.execute(
        sa.text(
            """
            UPDATE process_ai_prompts AS previous
            SET is_active = true
            WHERE previous.task_type = 'VOICE_CALL_AGENT'
              AND previous.source_prompt_id IN (
                  CAST(:v2_id AS uuid), CAST(:v3_id AS uuid)
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM process_ai_prompts AS active
                  WHERE active.process_id = previous.process_id
                    AND active.task_type = 'VOICE_CALL_AGENT'
                    AND active.is_active = true
              )
            """
        ).bindparams(v2_id=_VOICE_PROMPT_V2_ID, v3_id=_VOICE_PROMPT_V3_ID)
    )
