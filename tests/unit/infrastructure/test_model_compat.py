from src.infrastructure.ai.model_compat import chat_completion_options


def test_luna_uses_low_reasoning_and_completion_limit() -> None:
    options = chat_completion_options(
        "gpt-5.6-luna",
        temperature=0.2,
        max_tokens=4096,
    )

    assert options == {
        "reasoning_effort": "low",
        "max_completion_tokens": 4096,
    }


def test_legacy_model_keeps_temperature_and_max_tokens() -> None:
    options = chat_completion_options("gpt-4o", temperature=0.2, max_tokens=512)

    assert options == {"temperature": 0.2, "max_tokens": 512}
