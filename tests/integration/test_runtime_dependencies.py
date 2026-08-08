import os
import uuid

import pytest
from sqlalchemy import text

from src.infrastructure.cache.redis_client import redis_client
from src.infrastructure.db.database import engine

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Requiere PostgreSQL con pgvector y Redis",
)


async def test_migrations_pgvector_and_redis_are_ready():
    async with engine.connect() as connection:
        revision = (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar()
        extension = (
            await connection.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
        ).scalar()

    assert revision
    assert extension == "vector"
    assert await redis_client.ping() is True


async def test_synthetic_candidate_round_trip_rolls_back():
    user_id = uuid.uuid4()
    process_id = uuid.uuid4()
    candidate_id = uuid.uuid4()
    process_candidate_id = uuid.uuid4()

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (id, name, last_name, email, password_hash, role, status)
                    VALUES (:id, 'Admin', 'QA', :email, 'not-a-real-hash', 'ADMIN', 'ACTIVE')
                    """
                ),
                {"id": user_id, "email": f"qa-{user_id}@example.test"},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO hiring_processes
                      (id, name, job_title, area, seniority, status, budget_max_usd, recruiter_id)
                    VALUES
                      (:id, 'Proceso QA', 'Backend Engineer', 'Tecnologia', 'Senior',
                       'DRAFT', 50, :recruiter_id)
                    """
                ),
                {"id": process_id, "recruiter_id": user_id},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO candidates (id, name, last_name, email, cv_file_url)
                    VALUES (:id, 'Ada', 'Lovelace', :email, 'r2://qa/cv.pdf')
                    """
                ),
                {"id": candidate_id, "email": f"candidate-{candidate_id}@example.test"},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO process_candidates (id, process_id, candidate_id, status)
                    VALUES (:id, :process_id, :candidate_id, 'LOADED')
                    """
                ),
                {
                    "id": process_candidate_id,
                    "process_id": process_id,
                    "candidate_id": candidate_id,
                },
            )
            result = (
                await connection.execute(
                    text(
                        """
                        SELECT c.name, pc.status
                        FROM process_candidates pc
                        JOIN candidates c ON c.id = pc.candidate_id
                        WHERE pc.id = :id
                        """
                    ),
                    {"id": process_candidate_id},
                )
            ).one()
            assert result == ("Ada", "LOADED")
        finally:
            await transaction.rollback()
