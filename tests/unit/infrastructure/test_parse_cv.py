import importlib
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.db.models import (
    Candidate,
    CandidateCVVersion,
    CandidateStatus,
    ProcessCandidate,
)


def test_get_embedding_does_not_require_provider_response_id() -> None:
    module = importlib.import_module("src.infrastructure.workers.tasks.parse_cv")
    client = MagicMock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1, 0.2])],
        usage=SimpleNamespace(prompt_tokens=7),
    )

    embedding, tokens = module._get_embedding("perfil", client)

    assert embedding == [0.1, 0.2]
    assert tokens == 7


def test_normalized_cv_filename_uses_language_candidate_and_role() -> None:
    module = importlib.import_module("src.infrastructure.workers.tasks.parse_cv")

    assert (
        module._normalized_cv_filename("en", "María José / Gómez", "Senior Data Analyst")
        == "EN_Maria-Jose-Gomez_Senior-Data-Analyst.pdf"
    )
    assert module._normalized_cv_filename("es", "", "") == "ES_Candidato_Rol.pdf"


@pytest.mark.parametrize(
    ("content", "finish_reason", "refusal", "retryable"),
    [("", "stop", None, True), ("{", "stop", None, True),
     ("{}", "length", None, True), (None, "stop", "rechazo", False)],
)
def test_invalid_provider_response_is_classified(content, finish_reason, refusal, retryable):
    module = importlib.import_module("src.infrastructure.workers.tasks.parse_cv")
    response = SimpleNamespace(
        id="response-test", usage=None,
        choices=[SimpleNamespace(finish_reason=finish_reason,
                                 message=SimpleNamespace(content=content, refusal=refusal))],
    )
    with pytest.raises(module.CVResponseError) as caught:
        module._parse_response(response, "gpt-5.6-luna", "CV_EXTRACTION")
    assert caught.value.retryable is retryable
    assert caught.value.response is response


def test_charged_response_is_recorded_before_json_validation():
    module = importlib.import_module("src.infrastructure.workers.tasks.parse_cv")
    response = SimpleNamespace(
        id="response-test", usage=None,
        choices=[SimpleNamespace(finish_reason="length",
                                 message=SimpleNamespace(content="{", refusal=None))],
    )
    client = MagicMock()
    client.chat.completions.create.return_value = response
    record = MagicMock()
    with pytest.raises(module.CVResponseError):
        module._call_openai([], client, "prompt", "gpt-5.6-luna", on_response=record)
    record.assert_called_once_with(response)


def test_extraction_forwards_the_retry_token_limit():
    module = importlib.import_module("src.infrastructure.workers.tasks.parse_cv")
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        id="response-test", usage=None,
        choices=[SimpleNamespace(finish_reason="stop",
                                 message=SimpleNamespace(content='{"name":"test"}', refusal=None))],
    )
    module._call_openai([], client, "prompt", "gpt-5.6-luna", max_tokens=8192)
    assert client.chat.completions.create.call_args.kwargs["max_completion_tokens"] == 8192


def test_stale_task_cannot_process_a_candidate():
    module = importlib.import_module("src.infrastructure.workers.tasks.parse_cv")
    candidate_id, process_id, pc_id, cv_id = (uuid.uuid4() for _ in range(4))
    candidate = Candidate(id=candidate_id, name="Ejemplo", last_name="Prueba",
                          email="example@example.com", cv_file_url="cv.pdf")
    cv = CandidateCVVersion(id=cv_id, candidate_id=candidate_id, original_file_url="cv.pdf")
    pc = ProcessCandidate(id=pc_id, process_id=process_id, candidate_id=candidate_id,
                          cv_version_id=cv_id, status=CandidateStatus.CV_PROCESSING.value,
                          cv_task_id="new-task")
    session = _Session(candidate, pc, cv)
    task = SimpleNamespace(request=SimpleNamespace(id="old-task", retries=0), max_retries=2)
    with (patch.object(module, "_SyncSession", return_value=session),
          patch.object(module, "download_file_sync") as download):
        result = module._parse_cv(task, str(candidate_id), str(pc_id), str(process_id))
    assert "skipped" in result
    assert pc.status == CandidateStatus.CV_PROCESSING.value
    download.assert_not_called()


@pytest.mark.parametrize("retries", [0, 2])
def test_failure_keeps_claim_until_last_attempt(retries):
    module = importlib.import_module("src.infrastructure.workers.tasks.parse_cv")
    candidate_id, process_id, pc_id, cv_id = (uuid.uuid4() for _ in range(4))
    candidate = Candidate(id=candidate_id, name="Ejemplo", last_name="Prueba",
                          email="example@example.com", cv_file_url="cv.pdf")
    cv = CandidateCVVersion(id=cv_id, candidate_id=candidate_id, original_file_url="cv.pdf")
    pc = ProcessCandidate(id=pc_id, process_id=process_id, candidate_id=candidate_id,
                          cv_version_id=cv_id, status=CandidateStatus.CV_PROCESSING.value,
                          cv_task_id="task")
    session = _Session(candidate, pc, cv)
    task = MagicMock(request=SimpleNamespace(id="task", retries=retries), max_retries=2)
    task.retry.side_effect = RuntimeError("scheduled")
    with (patch.object(module, "_SyncSession", return_value=session),
          patch.object(module, "download_file_sync", side_effect=ValueError("falló")),
          patch.object(module, "sync_process_status_sync")):
        with pytest.raises(RuntimeError if retries == 0 else ValueError):
            module._parse_cv(task, str(candidate_id), str(pc_id), str(process_id))
    assert pc.status == (CandidateStatus.CV_PROCESSING.value if retries == 0
                         else CandidateStatus.CV_ERROR.value)
    assert pc.cv_task_id == ("task" if retries == 0 else None)


class _Query:
    def __init__(self, candidate: Candidate) -> None:
        self._candidate = candidate

    def filter(self, *args: object, **kwargs: object) -> "_Query":
        return self

    def first(self) -> Candidate:
        return self._candidate

    def update(self, *args: object, **kwargs: object) -> None:
        return None


class _Session:
    def __init__(
        self,
        original: Candidate,
        process_candidate: ProcessCandidate,
        cv_version: CandidateCVVersion,
    ) -> None:
        self.original = original
        self.process_candidate = process_candidate
        self.cv_version = cv_version
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.events: list[str] = []

    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, model: type, identifier: uuid.UUID) -> object:
        if model is Candidate:
            return self.original
        if model is ProcessCandidate:
            return self.process_candidate
        if model is CandidateCVVersion:
            return self.cv_version
        return None

    def query(self, model: type) -> _Query:
        return _Query(self.existing)

    def flush(self) -> None:
        return None

    def delete(self, value: object) -> None:
        self.deleted.append(value)

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.events.append("commit")

    def refresh(self, *args: object, **kwargs: object) -> None:
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
    existing.normalized_cv = {"full_name": "Perfil A"}
    cv_version = CandidateCVVersion(
        id=uuid.uuid4(),
        candidate_id=original_id,
        original_file_url="cvs/original.pdf",
    )
    process_candidate = ProcessCandidate(
        id=process_candidate_id,
        process_id=process_id,
        candidate_id=original_id,
        cv_version_id=cv_version.id,
        status=CandidateStatus.CV_PROCESSING.value,
        cv_task_id="task-test",
    )
    session = _Session(original, process_candidate, cv_version)
    session.existing = existing

    def _openai_result(
        *args: object, **kwargs: object
    ) -> tuple[dict, int, int, int, int, int, str]:
        session.events.append("openai")
        return (
            {"email": existing.email, "full_name": "Candidato Existente"},
            1,
            1,
            0,
            0,
            0,
            "chatcmpl-test",
        )

    def _record_cost(*args: object, **kwargs: object) -> bool:
        session.events.append("cost")
        return True

    with (
        patch.object(module, "_SyncSession", return_value=session),
        patch.object(module, "download_file_sync", return_value=b"pdf"),
        patch.object(module, "_prepare_content", return_value=[{"type": "text"}]),
        patch.object(module, "_get_openai", return_value=MagicMock()),
        patch.object(
            module,
            "_call_openai",
            side_effect=_openai_result,
        ),
        patch.object(
            module,
            "_call_translation_openai",
            return_value=(
                {"email": existing.email, "full_name": "Existing Candidate"},
                1,
                1,
                0,
                0,
                0,
                "chatcmpl-translation",
            ),
        ),
        patch.object(module, "_get_embedding", side_effect=RuntimeError("sin embedding")),
        patch.object(module, "record_cost_sync", side_effect=_record_cost) as record_cost,
        patch.object(module, "render_normalized_cv", return_value=b"normalized"),
        patch.object(
            module, "upload_file_sync", return_value="cvs/existing_normalized.pdf"
        ) as upload_file_sync,
        patch.object(module, "sync_process_status_sync"),
        patch(
            "src.application.ai.process_prompt_resolver.get_effective_prompt_sync",
            return_value=SimpleNamespace(system_prompt_text="prompt"),
        ),
        patch(
            "src.infrastructure.cache.redis_client.get_active_ai_model_sync",
            return_value="gpt-4o",
        ),
    ):
        task = SimpleNamespace(request=SimpleNamespace(id="task-test", retries=0), max_retries=2)
        result = module._parse_cv(
            task,
            str(original_id),
            str(process_candidate_id),
            str(process_id),
        )

    assert result["candidate_id"] == str(existing_id)
    assert record_cost.call_args.kwargs["candidate_id"] == existing_id
    assert process_candidate.candidate_id == existing_id
    assert cv_version.candidate_id == existing_id
    assert cv_version.original_file_url == "cvs/original.pdf"
    assert cv_version.normalized_cv == {"email": existing.email, "full_name": "Candidato Existente"}
    assert existing.normalized_cv == {"full_name": "Perfil A"}
    assert [call.args[0] for call in upload_file_sync.call_args_list] == [
        f"cvs/{process_id}/{cv_version.id}/ES_Candidato-Existente_Rol.pdf",
        f"cvs/{process_id}/{cv_version.id}/EN_Candidato-Existente_Rol.pdf",
    ]
    openai_index = session.events.index("openai")
    cost_index = session.events.index("cost")
    assert "commit" in session.events[openai_index + 1 : cost_index]
