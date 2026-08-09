import pytest

from src.application.profiling.voice_config_resolver import resolve_voice_config
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.ai.prompts import VOICE_CALL_AGENT_BASE_PROMPT
from src.infrastructure.db.models import HiringProcess, QuestionSet


def _question_set(**overrides) -> QuestionSet:
    defaults = dict(
        default_agent_id="qs-agent",
        default_language="es",
        default_llm_model="gpt-4o",
        default_voice_id="qs-voice",
        default_tts_stability=0.3,
        default_tts_speed=1.0,
        default_tts_similarity_boost=0.7,
    )
    defaults.update(overrides)
    return QuestionSet(**defaults)


def _process(**overrides) -> HiringProcess:
    defaults = dict(
        voice_override_agent_id=None,
        voice_override_language=None,
        voice_override_llm_model=None,
        voice_override_voice_id=None,
        voice_override_tts_stability=None,
        voice_override_tts_speed=None,
        voice_override_tts_similarity_boost=None,
    )
    defaults.update(overrides)
    return HiringProcess(**defaults)


def test_uses_process_prompt_and_question_set_technical_defaults():
    config = resolve_voice_config(
        _question_set(),
        _process(),
        process_prompt="process-prompt",
        process_first_message="saludo-proceso",
    )

    assert config.agent_id == "qs-agent"
    assert config.system_prompt == "process-prompt"
    assert config.first_message == "saludo-proceso"
    assert config.language == "es"
    assert config.voice_id == "qs-voice"
    assert config.tts_stability == 0.3


def test_process_technical_override_takes_precedence_over_question_set_default():
    config = resolve_voice_config(
        _question_set(),
        _process(
            voice_override_voice_id="process-voice",
        ),
        process_prompt="process-prompt",
        process_first_message="saludo-proceso",
    )

    assert config.system_prompt == "process-prompt"
    assert config.voice_id == "process-voice"
    # campos sin override siguen usando el default del question set
    assert config.language == "es"


def test_first_message_comes_only_from_process_revision():
    config = resolve_voice_config(
        _question_set(),
        _process(),
        process_prompt="prompt",
        process_first_message="saludo-versionado",
    )

    assert config.first_message == "saludo-versionado"


@pytest.mark.parametrize("first_message", [None, "", "   "])
def test_missing_process_first_message_is_rejected(first_message):
    with pytest.raises(BusinessRuleException, match="saludo inicial"):
        resolve_voice_config(
            _question_set(),
            _process(),
            process_prompt="prompt",
            process_first_message=first_message,
        )


def test_missing_process_system_prompt_is_rejected():
    with pytest.raises(BusinessRuleException, match="instrucciones activas"):
        resolve_voice_config(
            _question_set(),
            _process(),
            process_prompt=" ",
            process_first_message="Hola",
        )


def test_adds_consent_instruction_when_status_is_known():
    config = resolve_voice_config(
        _question_set(),
        _process(),
        whatsapp_consent_status="TIMEOUT",
        process_prompt="prompt",
        process_first_message="Hola",
    )

    assert "consentimiento explícito" in config.system_prompt


def test_does_not_ask_again_after_whatsapp_consent():
    config = resolve_voice_config(
        _question_set(),
        _process(),
        whatsapp_consent_status="ACCEPTED",
        process_prompt="prompt",
        process_first_message="Hola",
    )

    assert "NO le vuelvas a pedir permiso" in config.system_prompt


def test_uses_settings_elevenlabs_agent_id_as_last_resort(monkeypatch):
    from src.application.profiling import voice_config_resolver

    monkeypatch.setattr(voice_config_resolver.settings, "elevenlabs_agent_id", "fallback-agent")

    config = resolve_voice_config(
        _question_set(default_agent_id=None),
        _process(voice_override_agent_id=None),
        process_prompt="prompt",
        process_first_message="Hola",
    )

    assert config.agent_id == "fallback-agent"


def test_process_prompt_requests_brief_feedback_after_each_answer():
    config = resolve_voice_config(
        _question_set(),
        _process(),
        process_prompt=VOICE_CALL_AGENT_BASE_PROMPT,
        process_first_message="Hola",
    )

    assert "Después de cada respuesta sustantiva" in config.system_prompt
    assert "una sola frase" in config.system_prompt
    assert "sin calificarlo, prometer resultados" in config.system_prompt
