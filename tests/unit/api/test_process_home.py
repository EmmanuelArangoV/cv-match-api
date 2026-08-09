from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.api.v1 import processes as processes_api
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.db.models import AITaskType


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _SummaryRow:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row


class _OptionRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, process_rows, summary_row, option_rows):
        self.responses = [
            _SummaryRow(summary_row),
            _Rows(process_rows),
            _OptionRows(option_rows),
        ]
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.responses.pop(0)


def _process(recruiter_id):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        name="Backend senior",
        job_title="Backend Engineer",
        area="Tecnología",
        seniority="Senior",
        status="MATCH_DONE",
        budget_max_usd=50,
        recruiter_id=recruiter_id,
        recruiter=SimpleNamespace(name="QA", last_name="Recruiter"),
        question_set_id=None,
        created_at=now,
        updated_at=now,
    )


def _progress(process_id):
    return SimpleNamespace(
        as_dict=lambda: {
            "process_id": str(process_id),
            "process_status": "MATCH_DONE",
            "stage": "MATCH_DONE",
            "stage_label": "Match realizado",
            "updated_at": datetime.now(UTC).isoformat(),
            "counts": {
                "cv_processing": 0,
                "match_processing": 0,
                "profiling_active": 0,
                "calls_active": 0,
            },
            "active_calls": [],
        }
    )


@pytest.mark.asyncio
async def test_home_scopes_recruiter_and_clamps_an_out_of_range_page(monkeypatch):
    recruiter_id = uuid4()
    process = _process(recruiter_id)
    db = _FakeDB(
        process_rows=[(process, "QA", "Recruiter", True)],
        summary_row=(11, 11, 25, 4),
        option_rows=[
            SimpleNamespace(area="Tecnología", id=recruiter_id, name="QA", last_name="Recruiter")
        ],
    )

    async def fake_progress_batch(_db, rows, has_job_descriptions):
        assert rows == [process]
        assert has_job_descriptions == {process.id: True}
        return {process.id: _progress(process.id)}

    monkeypatch.setattr(processes_api, "get_process_progress_batch", fake_progress_batch)

    response = await processes_api.list_home_processes(
        page=99,
        page_size=10,
        stage=None,
        recruiter_id=uuid4(),
        area=None,
        current_user=SimpleNamespace(id=recruiter_id, role="RECRUITER"),
        db=db,
    )

    assert response["pagination"] == {
        "page": 2,
        "page_size": 10,
        "total": 11,
        "total_pages": 2,
    }
    assert response["summary"] == {
        "active_processes": 11,
        "cv_processed": 25,
        "profiling_completed": 4,
    }
    assert response["items"][0]["process_id"] == str(process.id)
    summary_sql = str(db.statements[0])
    assert "hiring_processes.recruiter_id" in summary_sql
    assert "hiring_processes.status NOT IN" in summary_sql
    # Resumen/conteo, pagina y opciones; progreso agrega una sola consulta real.
    assert len(db.statements) == 3


@pytest.mark.asyncio
async def test_archived_stage_is_explicitly_queryable(monkeypatch):
    recruiter_id = uuid4()
    process = _process(recruiter_id)
    process.status = "ARCHIVED"
    db = _FakeDB(
        process_rows=[(process, "QA", "Recruiter", False)],
        summary_row=(1, 0, 3, 1),
        option_rows=[
            SimpleNamespace(area="Tecnología", id=recruiter_id, name="QA", last_name="Recruiter")
        ],
    )

    async def fake_progress_batch(_db, _rows, has_job_descriptions):
        assert has_job_descriptions == {process.id: False}
        progress = _progress(process.id)
        payload = progress.as_dict()
        payload.update(process_status="ARCHIVED", stage="ARCHIVED", stage_label="Archivado")
        return {process.id: SimpleNamespace(as_dict=lambda: payload)}

    monkeypatch.setattr(processes_api, "get_process_progress_batch", fake_progress_batch)
    response = await processes_api.list_home_processes(
        page=1,
        page_size=10,
        stage="ARCHIVED",
        recruiter_id=None,
        area=None,
        current_user=SimpleNamespace(id=uuid4(), role="ADMIN"),
        db=db,
    )

    assert response["items"][0]["progress"]["stage"] == "ARCHIVED"
    summary_sql = str(db.statements[0])
    assert "hiring_processes.status =" in summary_sql
    assert "CASE" not in summary_sql


@pytest.mark.asyncio
async def test_home_rejects_unknown_stage_before_querying_database():
    db = _FakeDB(process_rows=[], summary_row=(0, 0, 0, 0), option_rows=[])

    with pytest.raises(BusinessRuleException, match="etapa seleccionada"):
        await processes_api.list_home_processes(
            page=1,
            page_size=10,
            stage="UNKNOWN_STAGE",
            recruiter_id=None,
            area=None,
            current_user=SimpleNamespace(id=uuid4(), role="ADMIN"),
            db=db,
        )

    assert db.statements == []


def test_process_prompt_endpoint_accepts_only_communication_tasks():
    processes_api._require_process_prompt_task(AITaskType.WHATSAPP_MESSAGE)
    processes_api._require_process_prompt_task(AITaskType.VOICE_CALL_AGENT)

    for task_type in (
        AITaskType.CV_EXTRACTION,
        AITaskType.CV_MATCH,
        AITaskType.JD_ENHANCEMENT,
        AITaskType.VOICE_PROFILING,
    ):
        with pytest.raises(BusinessRuleException, match="solo puede administrarse"):
            processes_api._require_process_prompt_task(task_type)
