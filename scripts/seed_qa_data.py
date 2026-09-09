"""Carga un dataset sintetico e idempotente para QA local y staging."""

import asyncio
import os
import uuid

from sqlalchemy import text

from src.infrastructure.auth.password import hash_password
from src.infrastructure.db.database import engine

USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
USER_EMAIL = "admin@qa.example.com"
SET_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
QUESTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000003")
PROCESS_ID = uuid.UUID("00000000-0000-4000-8000-000000000004")
CANDIDATE_ID = uuid.UUID("00000000-0000-4000-8000-000000000005")
PROCESS_CANDIDATE_ID = uuid.UUID("00000000-0000-4000-8000-000000000006")
CV_VERSION_ID = uuid.UUID("00000000-0000-4000-8000-000000000007")


async def main() -> None:
    password = os.environ.get("QA_SEED_ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("QA_SEED_ADMIN_PASSWORD es obligatorio para cargar datos QA")

    password_hash = hash_password(password)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO users (id, name, last_name, email, password_hash, role, status)
                VALUES (:id, 'Admin', 'QA', :email, :password_hash, 'ADMIN', 'ACTIVE')
                ON CONFLICT (id) DO UPDATE
                SET email = EXCLUDED.email, password_hash = EXCLUDED.password_hash
                """
            ),
            {"id": USER_ID, "email": USER_EMAIL, "password_hash": password_hash},
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
                INSERT INTO candidate_cv_versions
                  (id, candidate_id, original_file_url, extracted_profile)
                SELECT :id, id, cv_file_url, extracted_profile
                FROM candidates
                WHERE id = :candidate_id
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": CV_VERSION_ID, "candidate_id": CANDIDATE_ID},
        )
        await connection.execute(
            text(
                """
                INSERT INTO process_candidates
                  (id, process_id, candidate_id, status, match_percentage, match_category,
                   whatsapp_consent_status, availability_preference, cv_version_id)
                VALUES
                  (:id, :process_id, :candidate_id, 'MATCHED', 91, 'HIGH', 'ACCEPTED',
                   '{"timezone": "America/Bogota", "days": ["monday"]}'::jsonb, :cv_version_id)
                ON CONFLICT (id) DO UPDATE SET cv_version_id = EXCLUDED.cv_version_id
                """
            ),
            {
                "id": PROCESS_CANDIDATE_ID,
                "process_id": PROCESS_ID,
                "candidate_id": CANDIDATE_ID,
                "cv_version_id": CV_VERSION_ID,
            },
        )

    print(f"Dataset QA listo para {USER_EMAIL}")


if __name__ == "__main__":
    asyncio.run(main())
