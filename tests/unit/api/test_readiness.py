from unittest.mock import AsyncMock

import pytest

from src.api import readiness as readiness_module


@pytest.mark.parametrize(
    ("database_error", "redis_error", "expected_status"),
    [
        (None, None, 200),
        (RuntimeError("database"), None, 503),
        (None, RuntimeError("redis"), 503),
    ],
)
async def test_readiness_reports_dependency_state(
    monkeypatch, database_error, redis_error, expected_status
):
    database = AsyncMock(side_effect=database_error)
    redis = AsyncMock(side_effect=redis_error)
    monkeypatch.setattr(readiness_module, "check_database", database)
    monkeypatch.setattr(readiness_module, "check_redis", redis)

    response = await readiness_module.readiness()

    assert response.status_code == expected_status
    assert b"database" in response.body
    assert b"redis" in response.body
