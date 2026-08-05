import importlib
import uuid
from unittest.mock import MagicMock, patch

from src.infrastructure.db.models import Candidate, CandidateStatus, ProcessCandidate


class _Query:
    def __init__(self, candidate: Candidate) -> None:
        self._candidate = candidate

    def filter(self, *args: object, **kwargs: object) -> "_Query":
        return self

    def first(self) -> Candidate:
        return self._candidate


class _Session:
    def __init__(self, original: Candidate, process_candidate: ProcessCandidate) -> None:
        self.original = original
        self.process_candidate = process_candidate
        self.added: list[object] = []
        self.deleted: list[object] = []

    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, model: type, identifier: uuid.UUID) -> object:
        if model is Candidate:
            return self.original
        return self.process_candidate

    def query(self, model: type) -> _Query:
        return _Query(self.existing)

    def flush(self) -> None:
        return None

    def delete(self, value: object) -> None:
        self.deleted.append(value)

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_parse_cv_registers_cost_against_deduplicated_candidate() -> None:
    module = importlib.import_module("src.infrastructure.workers.tasks.parse_cv")
    original_id = uuid.uuid4()
    existing_id = uuid.uuid4()
    process_id = uuid.uuid4()
    process_candidate_id = uuid.uuid4()

    original = Candidate(
        id=original_id,
        name="Procesando",
        last_name="CV",
        email=f"pending_{original_id}@placeholder.riwi",
        cv_file_url="cvs/original.pdf",
    )
    existing = Candidate(
        id=existing_id,
        name="Candidato",
        last_name="Existente",
        email="candidate@example.com",
        cv_file_url="cvs/existing.pdf",
    )
    process_candidate = ProcessCandidate(
        id=process_candidate_id,
        process_id=process_id,
        candidate_id=original_id,
        status=CandidateStatus.CV_PROCESSING.value,
    )
    session = _Session(original, process_candidate)
    session.existing = existing

    with (
        patch.object(module, "_SyncSession", return_value=session),
        patch.object(module, "download_file_sync", return_value=b"pdf"),
        patch.object(module, "_prepare_content", return_value=[{"type": "text"}]),
        patch.object(module, "_get_openai", return_value=MagicMock()),
        patch.object(
            module,
            "_call_openai",
            return_value=({"email": existing.email, "full_name": "Candidato Existente"}, 1, 1),
        ),
        patch.object(module, "_get_embedding", return_value=[0.0]),
        patch.object(module, "render_normalized_cv", return_value=b"normalized"),
        patch.object(module, "upload_file_sync", return_value="cvs/existing_normalized.pdf"),
        patch.object(module, "sync_process_status_sync"),
        patch(
            "src.infrastructure.cache.redis_client.get_active_ai_prompt_sync",
            return_value="prompt",
        ),
        patch(
            "src.infrastructure.cache.redis_client.get_active_ai_model_sync",
            return_value="gpt-4o",
        ),
    ):
        result = module.parse_cv.run(
            str(original_id),
            str(process_candidate_id),
            str(process_id),
        )

    cost_log = session.added[0]
    assert result["candidate_id"] == str(existing_id)
    assert cost_log.candidate_id == existing_id
    assert process_candidate.candidate_id == existing_id
