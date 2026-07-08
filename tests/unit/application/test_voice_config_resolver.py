from src.application.profiling.voice_config_resolver import resolve_voice_config
from src.infrastructure.db.models import HiringProcess, QuestionSet


def _question_set(**overrides) -> QuestionSet:
    defaults = dict(
        default_agent_id="qs-agent",
        default_system_prompt="qs-prompt",
        default_first_message="qs-first",
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
        voice_override_system_prompt=None,
        voice_override_first_message=None,
        voice_override_language=None,
        voice_override_llm_model=None,
        voice_override_voice_id=None,
        voice_override_tts_stability=None,
        voice_override_tts_speed=None,
        voice_override_tts_similarity_boost=None,
    )
    defaults.update(overrides)
    return HiringProcess(**defaults)


def test_falls_back_to_question_set_defaults_when_no_override():
    config = resolve_voice_config(_question_set(), _process())

    assert config.agent_id == "qs-agent"
    assert config.system_prompt == "qs-prompt"
    assert config.language == "es"
    assert config.voice_id == "qs-voice"
    assert config.tts_stability == 0.3


def test_process_override_takes_precedence_over_question_set_default():
    config = resolve_voice_config(
        _question_set(),
        _process(
            voice_override_system_prompt="process-prompt",
            voice_override_voice_id="process-voice",
        ),
    )

    assert config.system_prompt == "process-prompt"
    assert config.voice_id == "process-voice"
    # campos sin override siguen usando el default del question set
    assert config.language == "es"


def test_uses_settings_elevenlabs_agent_id_as_last_resort(monkeypatch):
    from src.application.profiling import voice_config_resolver

    monkeypatch.setattr(voice_config_resolver.settings, "elevenlabs_agent_id", "fallback-agent")

    config = resolve_voice_config(
        _question_set(default_agent_id=None), _process(voice_override_agent_id=None)
    )

    assert config.agent_id == "fallback-agent"
