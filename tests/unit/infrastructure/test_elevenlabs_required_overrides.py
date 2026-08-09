import pytest

from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.voice import elevenlabs_client


def test_preload_requires_prompt_and_first_message_overrides(monkeypatch) -> None:
    monkeypatch.setattr(
        elevenlabs_client,
        "_get_allowed_overrides",
        lambda _agent_id: {"prompt": True, "first_message": False},
    )

    with pytest.raises(BusinessRuleException, match="first_message"):
        elevenlabs_client.preload_agent_overrides("agent-test")


def test_preload_accepts_complete_process_owned_voice_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        elevenlabs_client,
        "_get_allowed_overrides",
        lambda _agent_id: {"prompt": True, "first_message": True},
    )

    elevenlabs_client.preload_agent_overrides("agent-test")
