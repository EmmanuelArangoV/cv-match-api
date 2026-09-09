from types import SimpleNamespace
from uuid import uuid4

from src.application.ai.process_prompt_resolver import (
    GLOBAL_RUNTIME_PROMPT_TASKS,
    PROCESS_PROMPT_TASKS,
    get_effective_prompt_sync,
)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, prompt):
        self.prompt = prompt
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return _ScalarResult(self.prompt)


def test_prompt_task_ownership_is_explicit_and_complete():
    assert set(GLOBAL_RUNTIME_PROMPT_TASKS) == {
        "CV_EXTRACTION",
        "CV_TRANSLATION",
        "CV_MATCH",
        "JD_ENHANCEMENT",
        "VOICE_PROFILING",
    }
    assert set(PROCESS_PROMPT_TASKS) == {"WHATSAPP_MESSAGE", "VOICE_CALL_AGENT"}
    assert set(GLOBAL_RUNTIME_PROMPT_TASKS).isdisjoint(PROCESS_PROMPT_TASKS)


def test_existing_process_uses_global_active_prompt_for_match():
    prompt = SimpleNamespace(system_prompt_text="global-match")
    session = _FakeSession(prompt)

    resolved = get_effective_prompt_sync(session, uuid4(), "CV_MATCH")

    assert resolved is prompt
    sql = str(session.statement)
    assert "FROM ai_prompts" in sql
    assert "process_ai_prompts" not in sql


def test_communication_prompt_remains_scoped_to_process():
    prompt = SimpleNamespace(system_prompt_text="process-call", first_message_text="Hola")
    session = _FakeSession(prompt)

    resolved = get_effective_prompt_sync(session, uuid4(), "VOICE_CALL_AGENT")

    assert resolved is prompt
    sql = str(session.statement)
    assert "FROM process_ai_prompts" in sql
    assert "process_ai_prompts.process_id" in sql
