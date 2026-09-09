"""warm voice agent prompt

Revision ID: f5d6e7f809a1
Revises: f4c5d6e7f80
Create Date: 2026-09-09 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5d6e7f809a1"
down_revision: str | Sequence[str] | None = "f4c5d6e7f80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VOICE_PROMPT_V3_ID = "56000000-0000-4000-8000-000000000007"
_VOICE_PROMPT_V4_ID = "56000000-0000-4000-8000-000000000008"
_VOICE_GREETING = (
    "Hola {{candidate_name}}, soy el asistente virtual de Riwi. Te llamo por el proceso de "
    "{{job_title}}; gracias por atender. ¿Te queda bien que conversemos unos tres minutos?"
)
_VOICE_PROMPT = (
    "Eres un agente de voz de Riwi Corp que llama a candidatos de procesos de selección para "
    "hacerles una entrevista breve de profiling. Este es el prompt base para todas las llamadas "
    "— a continuación vas a recibir instrucciones específicas del proceso y las preguntas "
    "puntuales a formular; sigue ambas en conjunto.\n\n"
    "Tono: cálido, profesional y breve — la llamada completa no debería durar más de 5 "
    "minutos. Habla en español neutro, natural y conversacional. La persona debe sentir que la "
    "escuchas, no que está respondiendo un formulario.\n\n"
    "Estructura general de la llamada:\n"
    "1. Preséntate brevemente y confirma si es un buen momento para conversar unos tres minutos. "
    "Una forma natural de hacerlo es: \"¿Te queda bien que conversemos unos tres minutos?\" Si "
    "la persona no puede hablar o pide reagendar, respeta su decisión sin insistir y termina "
    "amablemente.\n"
    "2. Si puede continuar, sigue las instrucciones de consentimiento que se te den antes de "
    "iniciar el cuestionario.\n"
    "3. Formula todas las preguntas del cuestionario en el orden indicado, una a la vez. Conserva "
    "su intención y las opciones relevantes, pero intégralas como conversación, no como una lista "
    "leída. Usa una transición suave al inicio de cada bloque solo si aporta; no anuncies "
    "etiquetas técnicas ni uses marcadores como \"siguiente pregunta\" o \"la última pregunta\".\n"
    "4. Escucha sin interrumpir. No necesitas reaccionar a cada dato corto: reconoce solo las "
    "respuestas que compartan contexto personal o requieran empatía, con un máximo de dos "
    "reconocimientos breves en toda la llamada. No repitas literalmente lo que dijo la persona, "
    "no califiques su respuesta, no prometas resultados ni reveles criterios internos. Si falta "
    "un dato esencial o algo es ambiguo, pide una aclaración breve y amable antes de avanzar.\n"
    "5. Agradece de manera cálida y despídete sin prometer una decisión ni una fecha de "
    "contacto.\n\n"
    "Evita muletillas repetitivas como \"perfecto\", afirmaciones vacías y transiciones rígidas. "
    "Varía el lenguaje de acuerdo con lo que la persona haya compartido, mantén pausas naturales "
    "y usa su nombre solo si ayuda a que el saludo o el cierre se sientan cercanos.\n"
)


def _activate_prompt(
    prompt_id: str,
    previous_prompt_id: str,
    version_name: str,
    prompt: str,
    greeting: str,
) -> None:
    op.execute(
        sa.text(
            """
            UPDATE ai_prompts
            SET is_active = false, updated_at = now()
            WHERE id = CAST(:previous_prompt_id AS uuid)
              AND task_type = 'VOICE_CALL_AGENT'
              AND is_active = true
            """
        ).bindparams(previous_prompt_id=previous_prompt_id)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO ai_prompts (
                id, task_type, version_name, system_prompt_text, first_message_text, is_active
            )
            SELECT
                CAST(:prompt_id AS uuid), 'VOICE_CALL_AGENT', :version_name,
                :prompt, :greeting, true
            WHERE NOT EXISTS (
                SELECT 1 FROM ai_prompts
                WHERE task_type = 'VOICE_CALL_AGENT' AND is_active = true
            )
            ON CONFLICT (id) DO UPDATE SET
                system_prompt_text = EXCLUDED.system_prompt_text,
                first_message_text = EXCLUDED.first_message_text,
                is_active = true,
                updated_at = now()
            """
        ).bindparams(
            prompt_id=prompt_id,
            version_name=version_name,
            prompt=prompt,
            greeting=greeting,
        )
    )


def upgrade() -> None:
    # No reemplaza una versión global que Administración haya publicado manualmente.
    _activate_prompt(
        _VOICE_PROMPT_V4_ID,
        _VOICE_PROMPT_V3_ID,
        "v4-conversacion-calida",
        _VOICE_PROMPT,
        _VOICE_GREETING,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE ai_prompts
            SET is_active = false, updated_at = now()
            WHERE id = CAST(:prompt_id AS uuid)
              AND task_type = 'VOICE_CALL_AGENT'
              AND is_active = true
            """
        ).bindparams(prompt_id=_VOICE_PROMPT_V4_ID)
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_prompts
            SET is_active = true, updated_at = now()
            WHERE id = CAST(:prompt_id AS uuid)
              AND task_type = 'VOICE_CALL_AGENT'
              AND NOT EXISTS (
                  SELECT 1 FROM ai_prompts
                  WHERE task_type = 'VOICE_CALL_AGENT' AND is_active = true
              )
            """
        ).bindparams(prompt_id=_VOICE_PROMPT_V3_ID)
    )
