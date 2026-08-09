"""whatsapp templates and process-owned voice greetings

Revision ID: d8f2a4c6e9b1
Revises: c7a9e1f4b2d8
Create Date: 2026-08-09 11:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d8f2a4c6e9b1"
down_revision: str | Sequence[str] | None = "c7a9e1f4b2d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BOOTSTRAP_TEMPLATE_ID = "57000000-0000-4000-8000-000000000001"
_DEFAULT_GREETING = (
    "Hola {{candidate_name}}, soy el asistente virtual de Riwi. Te llamo por el proceso de "
    "{{job_title}}; gracias por atender."
)


def upgrade() -> None:
    op.create_table(
        "whatsapp_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meta_template_id", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("variable_bindings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meta_template_id"),
        sa.UniqueConstraint("name", "language", name="uq_whatsapp_templates_name_language"),
    )
    op.create_index(
        "uq_whatsapp_templates_default",
        "whatsapp_templates",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.add_column(
        "hiring_processes",
        sa.Column("whatsapp_template_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_hiring_processes_whatsapp_template",
        "hiring_processes",
        "whatsapp_templates",
        ["whatsapp_template_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # La integración anterior ya enviaba esta plantilla como si estuviera disponible. La primera
    # sincronización con Meta corrige inmediatamente el estado si cambió remotamente.
    op.execute(
        sa.text(
            """
            INSERT INTO whatsapp_templates (
                id, name, language, category, status, components, variable_bindings,
                is_enabled, is_default
            ) VALUES (
                CAST(:id AS uuid), 'autorizacion_llamada_ia_v2', 'es_CO', 'UTILITY', 'APPROVED',
                CAST(:components AS jsonb), CAST(:bindings AS jsonb), true, true
            )
            ON CONFLICT (name, language) DO NOTHING
            """
        ).bindparams(
            id=_BOOTSTRAP_TEMPLATE_ID,
            components=(
                '[{"type":"BODY","text":"Hola {{1}}, queremos solicitar tu autorización '
                'para una entrevista automatizada."},'
                '{"type":"BUTTONS","buttons":['
                '{"type":"QUICK_REPLY","text":"Sí, acepto"},'
                '{"type":"QUICK_REPLY","text":"No, gracias"}]}]'
            ),
            bindings='{"BODY":{"1":"candidate_name"}}',
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE hiring_processes
            SET whatsapp_template_id = CAST(:id AS uuid)
            WHERE whatsapp_template_id IS NULL
              AND EXISTS (SELECT 1 FROM whatsapp_templates WHERE id = CAST(:id AS uuid))
            """
        ).bindparams(id=_BOOTSTRAP_TEMPLATE_ID)
    )

    # Toda plantilla base de voz y toda revisión activa quedan completas antes de eliminar los
    # fallbacks históricos del proceso y del set de preguntas.
    op.execute(
        sa.text(
            """
            UPDATE ai_prompts
            SET first_message_text = :greeting
            WHERE task_type = 'VOICE_CALL_AGENT'
              AND (first_message_text IS NULL OR btrim(first_message_text) = '')
            """
        ).bindparams(greeting=_DEFAULT_GREETING)
    )
    op.execute(
        sa.text(
            """
            UPDATE process_ai_prompts AS prompt
            SET first_message_text = COALESCE(
                NULLIF(btrim(prompt.first_message_text), ''),
                NULLIF(btrim(process.voice_override_first_message), ''),
                NULLIF(btrim(question_set.default_first_message), ''),
                active_template.first_message_text,
                :greeting
            )
            FROM hiring_processes AS process
            LEFT JOIN question_sets AS question_set ON question_set.id = process.question_set_id
            LEFT JOIN ai_prompts AS active_template
              ON active_template.task_type = 'VOICE_CALL_AGENT'
             AND active_template.is_active = true
            WHERE prompt.process_id = process.id
              AND prompt.task_type = 'VOICE_CALL_AGENT'
              AND (prompt.first_message_text IS NULL OR btrim(prompt.first_message_text) = '')
            """
        ).bindparams(greeting=_DEFAULT_GREETING)
    )

    op.drop_column("question_sets", "default_first_message")
    op.drop_column("hiring_processes", "voice_override_first_message")


def downgrade() -> None:
    op.add_column("hiring_processes", sa.Column("voice_override_first_message", sa.Text()))
    op.add_column("question_sets", sa.Column("default_first_message", sa.Text()))
    op.execute(
        """
        UPDATE hiring_processes AS process
        SET voice_override_first_message = prompt.first_message_text
        FROM process_ai_prompts AS prompt
        WHERE prompt.process_id = process.id
          AND prompt.task_type = 'VOICE_CALL_AGENT'
          AND prompt.is_active = true
        """
    )
    op.drop_constraint(
        "fk_hiring_processes_whatsapp_template", "hiring_processes", type_="foreignkey"
    )
    op.drop_column("hiring_processes", "whatsapp_template_id")
    op.drop_index("uq_whatsapp_templates_default", table_name="whatsapp_templates")
    op.drop_table("whatsapp_templates")
