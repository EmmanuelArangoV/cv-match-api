"""add default first contact question set

Revision ID: f0c8d2a7e5b1
Revises: e9a1b2c3d4f5
Create Date: 2026-09-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0c8d2a7e5b1"
down_revision: str | Sequence[str] | None = "e9a1b2c3d4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


QUESTION_SET_ID = "b6f1f0e7-6167-4d74-9f2b-2c9493022051"
QUESTION_SET_NAME = "PROFILING TELEFÓNICO DE PRIMER ACERCAMIENTO — GENÉRICO (+ HABITUAL)"
QUESTION_SET_DESCRIPTION = (
    "Cuestionario predeterminado para la primera llamada de profiling. "
    "Cada proceso recibe una copia editable de esta plantilla."
)

QUESTIONS = (
    (
        "e4d45d9d-e9f2-4e63-b59b-e9c5d22f1e11",
        0,
        "Antes de continuar, ¿autorizas el tratamiento de tus datos personales durante esta "
        "llamada para fines del proceso de selección?",
        "YES_NO",
        "Autorización expresa de sí o no.",
        ["sí", "autorizo", "acepto"],
        ["no", "no autorizo", "no acepto"],
        True,
        "Registrar una autorización expresa o una negativa para revisión humana.",
    ),
    (
        "a4b8f793-d149-4c9e-bd90-8b7e0451f212",
        1,
        "¿Qué modalidades de trabajo tienes disponibles: remoto, híbrido o presencial?",
        "MULTIPLE_CHOICE",
        "Remoto, híbrido, presencial o una combinación de estas modalidades.",
        [],
        [],
        False,
        None,
    ),
    (
        "077a7c21-373d-4c41-89d6-9bdfd6407313",
        2,
        "¿Cuál es tu nivel de inglés: básico, intermedio o avanzado?",
        "MULTIPLE_CHOICE",
        "Básico, intermedio o avanzado.",
        [],
        [],
        False,
        None,
    ),
    (
        "3a64f78b-bceb-4d20-8a89-bf3ca7868d14",
        3,
        "¿Cuál es tu expectativa salarial en COP o USD para una vinculación indefinida, "
        "directa o contractor?",
        "OPEN",
        "Valor, moneda y modalidad de vinculación esperada.",
        [],
        [],
        False,
        None,
    ),
    (
        "1ca6c8cf-43c1-4dcc-bd5a-2d2fa7199d15",
        4,
        "Gracias por tus respuestas. Pronto nuestro Especialista de Adquisición de Talento "
        "se contactará contigo. Una última cosa: ¿cuál es tu disponibilidad para vincularte "
        "a un nuevo equipo: inmediata, dentro de una a dos semanas o en más de tres semanas?",
        "MULTIPLE_CHOICE",
        "Inmediata, dentro de una a dos semanas o en más de tres semanas.",
        [],
        [],
        False,
        None,
    ),
    (
        "ba3f5f1e-367c-4f44-9c26-0bbd90485c16",
        5,
        "¿Tienes algún compromiso personal, familiar o académico que pueda afectar tu proceso "
        "de vinculación durante los próximos tres meses?",
        "YES_NO",
        "Sí o no, con una explicación breve si aplica.",
        [],
        [],
        False,
        None,
    ),
)


def upgrade() -> None:
    # En entornos existentes se asigna como propietario el primer usuario disponible.
    # En una instalación nueva, el backend lo crea con el primer usuario que cree un proceso.
    op.execute(
        sa.text(
            """
            INSERT INTO question_sets (id, name, description, version, status, created_by)
            SELECT CAST(:question_set_id AS uuid), :name, :description, 1, 'ACTIVE', users.id
            FROM users
            WHERE NOT EXISTS (
                SELECT 1 FROM question_sets WHERE id = CAST(:question_set_id AS uuid)
            )
            ORDER BY CASE users.role WHEN 'ADMIN' THEN 0 ELSE 1 END, users.created_at
            LIMIT 1
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            question_set_id=QUESTION_SET_ID,
            name=QUESTION_SET_NAME,
            description=QUESTION_SET_DESCRIPTION,
        )
    )

    for (
        question_id,
        order_index,
        text,
        question_type,
        expected_answer,
        positive_keywords,
        risk_keywords,
        is_critical,
        eval_criteria,
    ) in QUESTIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO profiling_questions (
                    id, question_set_id, order_index, text, type, expected_answer,
                    positive_keywords, risk_keywords, weight, is_critical, eval_criteria
                )
                SELECT
                    CAST(:question_id AS uuid), CAST(:question_set_id AS uuid), :order_index,
                    :text, :question_type, :expected_answer,
                    CAST(:positive_keywords AS text[]), CAST(:risk_keywords AS text[]),
                    10, :is_critical, :eval_criteria
                WHERE EXISTS (
                    SELECT 1 FROM question_sets WHERE id = CAST(:question_set_id AS uuid)
                )
                ON CONFLICT (id) DO NOTHING
                """
            ).bindparams(
                question_id=question_id,
                question_set_id=QUESTION_SET_ID,
                order_index=order_index,
                text=text,
                question_type=question_type,
                expected_answer=expected_answer,
                positive_keywords=positive_keywords,
                risk_keywords=risk_keywords,
                is_critical=is_critical,
                eval_criteria=eval_criteria,
            )
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM question_sets WHERE id = CAST(:question_set_id AS uuid)").bindparams(
            question_set_id=QUESTION_SET_ID
        )
    )
