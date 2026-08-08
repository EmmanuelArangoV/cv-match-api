"""activate gpt 5.6 luna and brief voice feedback

Revision ID: a1c3e5f7b9d2
Revises: f9b2c4d6e8a0
Create Date: 2026-08-08 20:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c3e5f7b9d2"
down_revision: str | Sequence[str] | None = "f9b2c4d6e8a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODEL_IDS = {
    "CV_EXTRACTION": "56000000-0000-4000-8000-000000000001",
    "CV_MATCH": "56000000-0000-4000-8000-000000000002",
    "JD_ENHANCEMENT": "56000000-0000-4000-8000-000000000003",
    "VOICE_PROFILING": "56000000-0000-4000-8000-000000000004",
    "WHATSAPP_MESSAGE": "56000000-0000-4000-8000-000000000005",
}
_PROMPT_ID = "56000000-0000-4000-8000-000000000006"
_VOICE_PROMPT = (
    "Eres un agente de voz de Riwi Corp que llama a candidatos de procesos de selección para "
    "hacerles una entrevista breve de profiling. Este es el prompt base para todas las llamadas "
    "— a continuación vas a recibir instrucciones específicas del proceso y las preguntas "
    "puntuales a formular; sigue ambas en conjunto.\n\n"
    "Tono: cálido, profesional y breve — la llamada completa no debería durar más de 5 "
    "minutos. Habla en español neutro, natural y conversacional, nunca leas como un robot.\n\n"
    "Estructura general de la llamada:\n"
    "1. Preséntate brevemente (quién eres, de qué empresa, para qué proceso llamas).\n"
    "2. Sigue las instrucciones de consentimiento que se te den a continuación antes de "
    "continuar.\n"
    "3. Formula las preguntas del cuestionario en el orden indicado, una a la vez, escuchando "
    "la respuesta completa antes de pasar a la siguiente.\n"
    "4. Después de cada respuesta sustantiva, da una retroalimentación breve y natural de una "
    "sola frase, basada únicamente en lo que dijo el candidato. Reconoce un punto concreto de su "
    "respuesta sin calificarlo, prometer resultados ni revelar criterios internos. Evita repetir "
    'muletillas como "perfecto"; si la respuesta no fue clara, pide una aclaración corta en vez '
    "de inventar información.\n"
    "5. Agradece al candidato y despídete cordialmente al terminar.\n\n"
    "Si el candidato pide más tiempo, no puede hablar en ese momento, o pide reagendar, respeta "
    "su decisión sin insistir y termina la llamada amablemente.\n"
)


def upgrade() -> None:
    tasks = tuple(_MODEL_IDS)
    op.execute(
        sa.text(
            """
            UPDATE ai_model_configurations
            SET is_active = false
            WHERE provider = 'OPENAI' AND task_type IN :tasks
            """
        ).bindparams(sa.bindparam("tasks", value=tasks, expanding=True))
    )
    for task_type, model_id in _MODEL_IDS.items():
        op.execute(
            sa.text(
                """
                INSERT INTO ai_model_configurations
                    (id, task_type, provider, model_name, is_active)
                VALUES (:id, :task_type, 'OPENAI', 'gpt-5.6-luna', true)
                ON CONFLICT (id) DO UPDATE SET
                    model_name = EXCLUDED.model_name,
                    is_active = true,
                    updated_at = now()
                """
            ).bindparams(id=model_id, task_type=task_type)
        )

    op.execute(
        sa.text(
            """
            UPDATE ai_prompts
            SET is_active = false
            WHERE task_type = 'VOICE_CALL_AGENT'
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO ai_prompts
                (id, task_type, version_name, system_prompt_text, is_active)
            VALUES
                (:id, 'VOICE_CALL_AGENT', 'v2-feedback-breve', :prompt, true)
            ON CONFLICT (id) DO UPDATE SET
                system_prompt_text = EXCLUDED.system_prompt_text,
                is_active = true,
                updated_at = now()
            """
        ).bindparams(id=_PROMPT_ID, prompt=_VOICE_PROMPT)
    )


def downgrade() -> None:
    model_ids = tuple(_MODEL_IDS.values())
    op.execute(
        sa.text(
            """
            UPDATE ai_model_configurations
            SET is_active = false
            WHERE id IN :model_ids
            """
        ).bindparams(sa.bindparam("model_ids", value=model_ids, expanding=True))
    )
    op.execute(
        sa.text(
            """
            WITH previous AS (
                SELECT DISTINCT ON (task_type) id
                FROM ai_model_configurations
                WHERE provider = 'OPENAI'
                  AND model_name = 'gpt-4o'
                  AND task_type IN :tasks
                ORDER BY task_type, updated_at DESC
            )
            UPDATE ai_model_configurations
            SET is_active = true
            WHERE id IN (SELECT id FROM previous)
            """
        ).bindparams(sa.bindparam("tasks", value=tuple(_MODEL_IDS), expanding=True))
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_prompts
            SET is_active = false
            WHERE id = :prompt_id
            """
        ).bindparams(prompt_id=_PROMPT_ID)
    )
    op.execute(
        sa.text(
            """
            WITH previous AS (
                SELECT id
                FROM ai_prompts
                WHERE task_type = 'VOICE_CALL_AGENT' AND id <> :prompt_id
                ORDER BY
                    CASE WHEN version_name = 'v1-inicial' THEN 0 ELSE 1 END,
                    created_at DESC
                LIMIT 1
            )
            UPDATE ai_prompts
            SET is_active = true
            WHERE id IN (SELECT id FROM previous)
            """
        ).bindparams(prompt_id=_PROMPT_ID)
    )
