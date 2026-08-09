"""scope AI prompts to individual hiring processes

Revision ID: b4d8e2c1f6a3
Revises: a1c3e5f7b9d2
Create Date: 2026-08-08 23:20:00
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4d8e2c1f6a3"
down_revision: str | Sequence[str] | None = "a1c3e5f7b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TASKS = (
    "CV_EXTRACTION",
    "CV_MATCH",
    "JD_ENHANCEMENT",
    "VOICE_PROFILING",
    "WHATSAPP_MESSAGE",
    "VOICE_CALL_AGENT",
)


def _fallbacks() -> dict[str, str]:
    # Se importan durante la migración para que el snapshot conserve exactamente las plantillas
    # de la versión de aplicación que introdujo el esquema, incluso si faltaba un seed antiguo.
    from src.application.candidate.whatsapp_message_usecase import _AGENT_SYSTEM_PROMPT
    from src.infrastructure.ai.prompts import (
        CV_EXTRACTION_PROMPT,
        JD_ANALYZE_ENHANCE_SYSTEM_PROMPT,
        MATCH_SYSTEM_PROMPT,
        PROFILING_EVALUATION_PROMPT,
        VOICE_CALL_AGENT_BASE_PROMPT,
    )

    return {
        "CV_EXTRACTION": CV_EXTRACTION_PROMPT,
        "CV_MATCH": MATCH_SYSTEM_PROMPT,
        "JD_ENHANCEMENT": JD_ANALYZE_ENHANCE_SYSTEM_PROMPT,
        "VOICE_PROFILING": PROFILING_EVALUATION_PROMPT,
        "WHATSAPP_MESSAGE": _AGENT_SYSTEM_PROMPT,
        "VOICE_CALL_AGENT": VOICE_CALL_AGENT_BASE_PROMPT,
    }


def upgrade() -> None:
    op.create_table(
        "process_ai_prompts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("process_id", sa.UUID(), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("version_name", sa.String(length=100), nullable=False),
        sa.Column("system_prompt_text", sa.TEXT(), nullable=False),
        sa.Column("source_prompt_id", sa.UUID(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["process_id"], ["hiring_processes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_prompt_id"], ["ai_prompts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_process_ai_prompts_active_task",
        "process_ai_prompts",
        ["process_id", "task_type"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    bind = op.get_bind()
    active_templates = {
        row["task_type"]: row
        for row in bind.execute(
            sa.text(
                "SELECT id, task_type, version_name, system_prompt_text "
                "FROM ai_prompts WHERE is_active = true"
            )
        ).mappings()
    }
    question_set_prompts = {
        row["id"]: row["default_system_prompt"]
        for row in bind.execute(
            sa.text("SELECT id, default_system_prompt FROM question_sets")
        ).mappings()
    }
    fallbacks = _fallbacks()
    # Las plantillas son solo puntos de partida para nuevos procesos/restauraciones. Aseguramos
    # una por tarea para que la migración no deje un proceso sin una ruta explícita de restore.
    for task_type in _TASKS:
        if task_type in active_templates:
            continue
        template_id = uuid.uuid4()
        prompt_text = fallbacks[task_type]
        bind.execute(
            sa.text(
                """
                INSERT INTO ai_prompts
                    (id, task_type, version_name, system_prompt_text, is_active)
                VALUES
                    (:id, :task_type, 'v1-inicial-migrada', :system_prompt_text, true)
                """
            ),
            {
                "id": template_id,
                "task_type": task_type,
                "system_prompt_text": prompt_text,
            },
        )
        active_templates[task_type] = {
            "id": template_id,
            "task_type": task_type,
            "version_name": "v1-inicial-migrada",
            "system_prompt_text": prompt_text,
        }
    processes = bind.execute(
        sa.text(
            "SELECT id, recruiter_id, question_set_id, voice_override_system_prompt "
            "FROM hiring_processes"
        )
    ).mappings()

    rows: list[dict] = []
    for process in processes:
        for task_type in _TASKS:
            template = active_templates.get(task_type)
            prompt_text = template["system_prompt_text"] if template else fallbacks[task_type]
            if task_type == "VOICE_CALL_AGENT":
                process_specific = (
                    process["voice_override_system_prompt"]
                    or question_set_prompts.get(process["question_set_id"])
                )
                if process_specific:
                    prompt_text = f"{prompt_text}\n\n{process_specific}"
            # WhatsApp no leía ai_prompts antes de este cambio; su snapshot siempre debe ser el
            # prompt que realmente ejecutaba el proceso, no un registro global posiblemente inerte.
            if task_type == "WHATSAPP_MESSAGE":
                prompt_text = fallbacks[task_type]
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "process_id": process["id"],
                    "task_type": task_type,
                    "version_name": "v1-migrada",
                    "system_prompt_text": prompt_text,
                    # El flujo histórico de WhatsApp usaba su prompt local; no afirmamos que
                    # proviene de una plantilla si el snapshot conserva ese comportamiento.
                    "source_prompt_id": (
                        template["id"] if template and task_type != "WHATSAPP_MESSAGE" else None
                    ),
                    "is_active": True,
                    "created_by": process["recruiter_id"],
                }
            )
    if rows:
        bind.execute(
            sa.text(
                """
                INSERT INTO process_ai_prompts
                    (id, process_id, task_type, version_name, system_prompt_text,
                     source_prompt_id, is_active, created_by)
                VALUES
                    (:id, :process_id, :task_type, :version_name, :system_prompt_text,
                     :source_prompt_id, :is_active, :created_by)
                """
            ),
            rows,
        )

    op.drop_column("hiring_processes", "voice_override_system_prompt")
    op.drop_column("question_sets", "default_system_prompt")


def downgrade() -> None:
    op.add_column("question_sets", sa.Column("default_system_prompt", sa.TEXT(), nullable=True))
    op.add_column(
        "hiring_processes", sa.Column("voice_override_system_prompt", sa.TEXT(), nullable=True)
    )
    op.drop_index("uq_process_ai_prompts_active_task", table_name="process_ai_prompts")
    op.drop_table("process_ai_prompts")
