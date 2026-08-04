import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.v1.candidates import analyze_cvs
from src.application.cv.use_cases import AnalyzeCVResult, AnalyzeCVsUseCase
from src.infrastructure.db.models import (
    CandidateStatus,
    HiringProcess,
    ProcessCandidate,
    ProcessStatus,
)


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


def _pc(status: CandidateStatus) -> ProcessCandidate:
    return ProcessCandidate(
        id=uuid.uuid4(),
        process_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        status=status.value,
    )


@pytest.mark.asyncio
async def test_analyze_enqueues_loaded_and_cv_error_and_claims_them():
    loaded = _pc(CandidateStatus.LOADED)
    errored = _pc(CandidateStatus.CV_ERROR)
    process_id = loaded.process_id
    errored.process_id = process_id
    db = AsyncMock()

    async def execute(_query):
        rows = [
            pc
            for pc in (loaded, errored)
            if pc.status in {CandidateStatus.LOADED.value, CandidateStatus.CV_ERROR.value}
        ]
        return _ScalarResult(rows)

    db.execute = AsyncMock(side_effect=execute)
    task = SimpleNamespace(id="task-1")

    with patch("src.application.cv.use_cases.parse_cv") as parse_cv:
        parse_cv.delay.return_value = task
        results = await AnalyzeCVsUseCase(db).execute(process_id)
        second_results = await AnalyzeCVsUseCase(db).execute(process_id)

    assert len(results) == 2
    assert second_results == []
    assert {result.task_id for result in results} == {"task-1"}
    assert {pc.status for pc in (loaded, errored)} == {CandidateStatus.CV_PROCESSING.value}
    assert parse_cv.delay.call_count == 2
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_analyze_does_not_requeue_processing_or_processed_candidates():
    processing = _pc(CandidateStatus.CV_PROCESSING)
    processed = _pc(CandidateStatus.MATCH_PENDING)
    process_id = processing.process_id
    processed.process_id = process_id
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult([]))

    with patch("src.application.cv.use_cases.parse_cv") as parse_cv:
        results = await AnalyzeCVsUseCase(db).execute(process_id)

    assert results == []
    parse_cv.delay.assert_not_called()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_restores_status_when_task_publish_fails():
    errored = _pc(CandidateStatus.CV_ERROR)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult([errored]))
    db.get = AsyncMock(return_value=errored)

    with patch("src.application.cv.use_cases.parse_cv") as parse_cv:
        parse_cv.delay.side_effect = RuntimeError("broker unavailable")
        results = await AnalyzeCVsUseCase(db).execute(errored.process_id)

    assert results[0].task_id is None
    assert results[0].error == "broker unavailable"
    assert errored.status == CandidateStatus.CV_ERROR.value
    db.rollback.assert_awaited_once()
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_analyze_endpoint_reports_queued_tasks_and_skipped_candidates():
    process_id = uuid.uuid4()
    queued_pc = _pc(CandidateStatus.CV_PROCESSING)
    queued_pc.process_id = process_id
    skipped_pc = _pc(CandidateStatus.MATCH_PENDING)
    skipped_pc.process_id = process_id
    process = HiringProcess(id=process_id, status=ProcessStatus.DRAFT.value)
    db = AsyncMock()
    db.get = AsyncMock(return_value=process)
    db.execute = AsyncMock(return_value=_ScalarResult([queued_pc, skipped_pc]))
    result = AnalyzeCVResult(
        process_candidate_id=queued_pc.id,
        candidate_id=queued_pc.candidate_id,
        previous_status=CandidateStatus.LOADED.value,
        task_id="task-1",
    )

    with (
        patch("src.api.v1.candidates.AnalyzeCVsUseCase") as use_case,
        patch("src.api.v1.candidates.sync_process_status", new_callable=AsyncMock),
    ):
        use_case.return_value.execute = AsyncMock(return_value=[result])
        response = await analyze_cvs(process_id, MagicMock(), db)

    assert response["queued"] == 1
    assert response["tasks"] == [
        {"process_candidate_id": str(queued_pc.id), "task_id": "task-1"}
    ]
    assert response["skipped"] == [
        {
            "process_candidate_id": str(skipped_pc.id),
            "status": CandidateStatus.MATCH_PENDING.value,
            "reason": "El candidato no está pendiente de análisis",
        }
    ]
