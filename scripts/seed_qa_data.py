"""Carga un dataset sintetico e idempotente para QA local y staging."""

import asyncio
import uuid

from sqlalchemy import text

from src.infrastructure.auth.password import hash_password
from src.infrastructure.db.database import engine

USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
SET_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
QUESTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000003")
PROCESS_ID = uuid.UUID("00000000-0000-4000-8000-000000000004")
CANDIDATE_ID = uuid.UUID("00000000-0000-4000-8000-000000000005")
PROCESS_CANDIDATE_ID = uuid.UUID("00000000-0000-4000-8000-000000000006")


async def main() -> None:
    password_hash = hash_password("QaOnly-2026!")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO users (id, name, last_name, email, password_hash, role, status)
                VALUES (:id, 'Admin', 'QA', 'admin@qa.test', :password_hash, 'ADMIN', 'ACTIVE')
                ON CONFLICT (id) DO UPDATE SET password_hash = EXCLUDED.password_hash
                """
            ),
            {"id": USER_ID, "password_hash": password_hash},
        )
        await connection.execute(
            text(
                """
                INSERT INTO question_sets
                  (id, name, description, version, status, created_by, default_language)
                VALUES
                  (:id, 'Set tecnico QA', 'Datos sinteticos', 1, 'DRAFT', :user_id, 'es')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": SET_ID, "user_id": USER_ID},
        )
        await connection.execute(
            text(
                """
                INSERT INTO profiling_questions
                  (id, question_set_id, order_index, text, type, positive_keywords,
                   risk_keywords, weight, is_critical)
                VALUES
                  (:id, :set_id, 0, 'Cuentanos tu experiencia con FastAPI', 'OPEN',
                   ARRAY['FastAPI'], ARRAY[]::text[], 100, true)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": QUESTION_ID, "set_id": SET_ID},
        )
        await connection.execute(
            text(
                """
                INSERT INTO hiring_processes
                  (id, name, job_title, area, seniority, status, budget_max_usd,
                   recruiter_id, question_set_id, voice_override_language)
                VALUES
                  (:id, 'Backend QA 2026', 'Backend Engineer', 'Tecnologia', 'Senior',
                   'MATCH_DONE', 50, :user_id, :set_id, 'es')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": PROCESS_ID, "user_id": USER_ID, "set_id": SET_ID},
        )
        await connection.execute(
            text(
                """
                INSERT INTO candidates
                  (id, name, last_name, email, phone, cv_file_url, extracted_profile)
                VALUES
                  (:id, 'Ada', 'Lovelace', 'ada@qa.test', '+15550000002',
                   'r2://qa/cv-ada.pdf', '{"city": "Medellin"}'::jsonb)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": CANDIDATE_ID},
        )
        await connection.execute(
            text(
                """
                INSERT INTO process_candidates
                  (id, process_id, candidate_id, status, match_percentage, match_category,
                   whatsapp_consent_status, availability_preference)
                VALUES
                  (:id, :process_id, :candidate_id, 'MATCHED', 91, 'HIGH', 'ACCEPTED',
                   '{"timezone": "America/Bogota", "days": ["monday"]}'::jsonb)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": PROCESS_CANDIDATE_ID,
                "process_id": PROCESS_ID,
                "candidate_id": CANDIDATE_ID,
            },
        )

    print("Dataset QA listo: admin@qa.test / QaOnly-2026!")


if __name__ == "__main__":
    asyncio.run(main())
