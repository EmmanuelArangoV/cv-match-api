from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.api.v1.metrics import get_home_metrics


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Rows(self.rows)


@pytest.mark.asyncio
async def test_admin_home_cost_keeps_logs_without_process_assignment():
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    db = _FakeDB([(today, 1.25)])

    response = await get_home_metrics(
        current_user=SimpleNamespace(id=uuid4(), role="ADMIN"),
        db=db,
    )

    assert response["monthly_cost_usd"] == 1.25
    assert response["daily_costs"] == [{"date": today.date().isoformat(), "cost": 1.25}]
    assert "JOIN hiring_processes" not in str(db.statement)


@pytest.mark.asyncio
async def test_recruiter_home_cost_is_scoped_through_its_processes():
    recruiter_id = uuid4()
    db = _FakeDB([])

    response = await get_home_metrics(
        current_user=SimpleNamespace(id=recruiter_id, role="RECRUITER"),
        db=db,
    )

    assert response == {"monthly_cost_usd": 0, "daily_costs": []}
    sql = str(db.statement)
    assert "JOIN hiring_processes" in sql
    assert "hiring_processes.recruiter_id" in sql
