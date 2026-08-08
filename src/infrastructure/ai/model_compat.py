"""Opciones compatibles por familia para Chat Completions de OpenAI."""

from typing import Any

DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"


def chat_completion_options(
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Evita enviar parámetros heredados incompatibles con modelos de razonamiento."""
    if model.startswith("gpt-5.6"):
        options: dict[str, Any] = {"reasoning_effort": "low"}
        if max_tokens is not None:
            options["max_completion_tokens"] = max_tokens
        return options

    options = {}
    if temperature is not None:
        options["temperature"] = temperature
    if max_tokens is not None:
        options["max_tokens"] = max_tokens
    return options
