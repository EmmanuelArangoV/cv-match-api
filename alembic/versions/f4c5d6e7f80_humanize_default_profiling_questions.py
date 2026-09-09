"""humanize default profiling questions and voice prompt

Revision ID: f4c5d6e7f80
Revises: f3c4d5e6f70
Create Date: 2026-09-09 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4c5d6e7f80"
down_revision: str | Sequence[str] | None = "f3c4d5e6f70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_QUESTION_SET_ID = "b6f1f0e7-6167-4d74-9f2b-2c9493022051"
_CONSENT_QUESTION_ID = "e4d45d9d-e9f2-4e63-b59b-e9c5d22f1e11"
_VOICE_PROMPT_V2_ID = "56000000-0000-4000-8000-000000000006"
_VOICE_PROMPT_V3_ID = "56000000-0000-4000-8000-000000000007"
_VOICE_GREETING = (
    "Hola {{candidate_name}}, soy el asistente virtual de Riwi. Te llamo por el proceso de "
    "{{job_title}}; gracias por atender."
)
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
    "la respuesta completa antes de pasar a la siguiente. Respeta los bloques conversacionales "
    "que recibas: usa una transición breve al inicio de cada bloque y nunca presentes cada "
    "pregunta con una etiqueta técnica.\n"
    "4. Después de cada respuesta sustantiva, da una retroalimentación breve y natural de una "
    "sola frase, basada únicamente en lo que dijo el candidato. Reconoce un punto concreto de su "
    "respuesta sin calificarlo, prometer resultados ni revelar criterios internos. Evita repetir "
    'muletillas como "perfecto"; si la respuesta no fue clara, pide una aclaración corta en vez '
    "de inventar información.\n"
    "5. Agradece al candidato y despídete cordialmente al terminar.\n\n"
    "Si el candidato pide más tiempo, no puede hablar en ese momento, o pide reagendar, respeta "
    "su decisión sin insistir y termina la llamada amablemente.\n"
)

_NEW_QUESTIONS = (
    (
        "a4b8f793-d149-4c9e-bd90-8b7e0451f212",
        0,
        "¿Qué modalidad de trabajo se ajusta mejor a tu disponibilidad actual: remoto, híbrido "
        "o presencial?",
        "MULTIPLE_CHOICE",
        "Remoto, híbrido, presencial o una combinación de estas modalidades.",
    ),
    (
        "077a7c21-373d-4c41-89d6-9bdfd6407313",
        1,
        "¿Cómo describirías tu nivel actual de inglés: básico, intermedio o avanzado?",
        "MULTIPLE_CHOICE",
        "Básico, intermedio o avanzado.",
    ),
    (
        "3a64f78b-bceb-4d20-8a89-bf3ca7868d14",
        2,
        "¿Cuál es tu expectativa salarial para esta oportunidad? Indícame el valor y la moneda "
        "que esperas.",
        "CLOSED",
        "Valor y moneda de la expectativa salarial.",
    ),
    (
        "1ca6c8cf-43c1-4dcc-bd5a-2d2fa7199d15",
        3,
        "¿Qué disponibilidad tienes para vincularte a un nuevo equipo: inmediata, dentro de una "
        "a dos semanas o después de ese periodo?",
        "MULTIPLE_CHOICE",
        "Inmediata, dentro de una a dos semanas o después de ese periodo.",
    ),
    (
        "ba3f5f1e-367c-4f44-9c26-0bbd90485c16",
        4,
        "Para entender tu disponibilidad de forma realista, ¿hay algún compromiso personal, "
        "familiar, académico u otro que pueda afectar tu vinculación durante los próximos tres "
        "meses?",
        "OPEN",
        "Explicación breve de cualquier compromiso y de su posible impacto, si aplica.",
    ),
)

_PREVIOUS_QUESTIONS = (
    (
        "a4b8f793-d149-4c9e-bd90-8b7e0451f212",
        1,
        "¿Qué modalidades de trabajo tienes disponibles: remoto, híbrido o presencial?",
        "MULTIPLE_CHOICE",
        "Remoto, híbrido, presencial o una combinación de estas modalidades.",
    ),
    (
        "077a7c21-373d-4c41-89d6-9bdfd6407313",
        2,
        "¿Cuál es tu nivel de inglés: básico, intermedio o avanzado?",
        "MULTIPLE_CHOICE",
        "Básico, intermedio o avanzado.",
    ),
    (
        "3a64f78b-bceb-4d20-8a89-bf3ca7868d14",
        3,
        "¿Cuál es tu expectativa salarial en COP o USD para una vinculación indefinida, directa "
        "o contractor?",
        "OPEN",
        "Valor, moneda y modalidad de vinculación esperada.",
    ),
    (
        "1ca6c8cf-43c1-4dcc-bd5a-2d2fa7199d15",
        4,
        "Gracias por tus respuestas. Pronto nuestro Especialista de Adquisición de Talento se "
        "contactará contigo. Una última cosa: ¿cuál es tu disponibilidad para vincularte a un "
        "nuevo equipo: inmediata, dentro de una a dos semanas o en más de tres semanas?",
        "MULTIPLE_CHOICE",
        "Inmediata, dentro de una a dos semanas o en más de tres semanas.",
    ),
    (
        "ba3f5f1e-367c-4f44-9c26-0bbd90485c16",
        5,
        "¿Tienes algún compromiso personal, familiar o académico que pueda afectar tu proceso "
        "de vinculación durante los próximos tres meses?",
        "YES_NO",
        "Sí o no, con una explicación breve si aplica.",
    ),
)


def _update_questions(questions: tuple[tuple[str, int, str, str, str], ...]) -> None:
    for question_id, order_index, text, question_type, expected_answer in questions:
        op.execute(
            sa.text(
                """
                UPDATE profiling_questions
                SET order_index = :order_index,
                    text = :text,
                    type = :question_type,
                    expected_answer = :expected_answer,
                    positive_keywords = CAST(:positive_keywords AS text[]),
                    risk_keywords = CAST(:risk_keywords AS text[]),
                    is_critical = false,
                    eval_criteria = NULL
                WHERE id = CAST(:question_id AS uuid)
                  AND question_set_id = CAST(:question_set_id AS uuid)
                """
            ).bindparams(
                question_id=question_id,
                question_set_id=_QUESTION_SET_ID,
                order_index=order_index,
                text=text,
                question_type=question_type,
                expected_answer=expected_answer,
                positive_keywords=[],
                risk_keywords=[],
            )
        )


def upgrade() -> None:
    # Solo evoluciona la plantilla ACTIVE. Los procesos tienen un clon propio y no se reescriben.
    op.execute(
        sa.text(
            """
            DELETE FROM profiling_questions
            WHERE id = CAST(:question_id AS uuid)
              AND question_set_id = CAST(:question_set_id AS uuid)
            """
        ).bindparams(question_id=_CONSENT_QUESTION_ID, question_set_id=_QUESTION_SET_ID)
    )
    _update_questions(_NEW_QUESTIONS)
    op.execute(
        sa.text(
            """
            UPDATE question_sets
            SET version = GREATEST(version, 2), updated_at = now()
            WHERE id = CAST(:question_set_id AS uuid)
            """
        ).bindparams(question_set_id=_QUESTION_SET_ID)
    )

    # Solo sustituye la plantilla estándar si sigue activa. Una versión publicada desde Admin
    # permanece como la decisión explícita de la organización.
    op.execute(
        sa.text(
            """
            UPDATE ai_prompts
            SET is_active = false, updated_at = now()
            WHERE id = CAST(:previous_prompt_id AS uuid)
              AND task_type = 'VOICE_CALL_AGENT'
              AND is_active = true
            """
        ).bindparams(previous_prompt_id=_VOICE_PROMPT_V2_ID)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO ai_prompts (
                id, task_type, version_name, system_prompt_text, first_message_text, is_active
            )
            SELECT
                CAST(:prompt_id AS uuid), 'VOICE_CALL_AGENT', 'v3-bloques-conversacionales',
                :prompt, :greeting, true
            WHERE NOT EXISTS (
                SELECT 1
                FROM ai_prompts
                WHERE task_type = 'VOICE_CALL_AGENT' AND is_active = true
            )
            ON CONFLICT (id) DO UPDATE SET
                system_prompt_text = EXCLUDED.system_prompt_text,
                first_message_text = EXCLUDED.first_message_text,
                is_active = true,
                updated_at = now()
            """
        ).bindparams(
            prompt_id=_VOICE_PROMPT_V3_ID,
            prompt=_VOICE_PROMPT,
            greeting=_VOICE_GREETING,
        )
    )


def downgrade() -> None:
    _update_questions(_PREVIOUS_QUESTIONS)
    op.execute(
        sa.text(
            """
            INSERT INTO profiling_questions (
                id, question_set_id, order_index, text, type, expected_answer,
                positive_keywords, risk_keywords, weight, is_critical, eval_criteria
            )
            SELECT
                CAST(:question_id AS uuid), CAST(:question_set_id AS uuid), 0,
                :text, 'YES_NO', :expected_answer,
                CAST(:positive_keywords AS text[]), CAST(:risk_keywords AS text[]),
                10, true, :eval_criteria
            WHERE EXISTS (
                SELECT 1 FROM question_sets WHERE id = CAST(:question_set_id AS uuid)
            )
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            question_id=_CONSENT_QUESTION_ID,
            question_set_id=_QUESTION_SET_ID,
            text=(
                "Antes de continuar, ¿autorizas el tratamiento de tus datos personales durante "
                "esta llamada para fines del proceso de selección?"
            ),
            expected_answer="Autorización expresa de sí o no.",
            positive_keywords=["sí", "autorizo", "acepto"],
            risk_keywords=["no", "no autorizo", "no acepto"],
            eval_criteria="Registrar una autorización expresa o una negativa para revisión humana.",
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE question_sets
            SET version = 1, updated_at = now()
            WHERE id = CAST(:question_set_id AS uuid)
            """
        ).bindparams(question_set_id=_QUESTION_SET_ID)
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_prompts
            SET is_active = false, updated_at = now()
            WHERE id = CAST(:prompt_id AS uuid)
              AND task_type = 'VOICE_CALL_AGENT'
              AND is_active = true
            """
        ).bindparams(prompt_id=_VOICE_PROMPT_V3_ID)
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_prompts
            SET is_active = true, updated_at = now()
            WHERE id = CAST(:previous_prompt_id AS uuid)
              AND task_type = 'VOICE_CALL_AGENT'
              AND NOT EXISTS (
                  SELECT 1
                  FROM ai_prompts
                  WHERE task_type = 'VOICE_CALL_AGENT' AND is_active = true
              )
            """
        ).bindparams(previous_prompt_id=_VOICE_PROMPT_V2_ID)
    )
