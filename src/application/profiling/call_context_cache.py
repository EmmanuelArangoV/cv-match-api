"""Contexto de llamada preparado antes de que el candidato conteste."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from src.application.profiling.voice_config_resolver import VoiceCallConfig
from src.infrastructure.cache.redis_client import redis_client, redis_client_sync

_CACHE_PREFIX = "profiling:call-context:"
_CACHE_TTL_SECONDS = 900


def build_dynamic_variables(candidate_name: str, job_title: str, process_id: str) -> dict[str, str]:
    return {"candidate_name": candidate_name, "job_title": job_title, "process_id": process_id}


def _key(run_id: str) -> str:
    return f"{_CACHE_PREFIX}{run_id}"


def _encode(
    voice_config: VoiceCallConfig,
    dynamic_variables: dict[str, str],
    to_number: str,
) -> str:
    return json.dumps(
        {
            "voice_config": asdict(voice_config),
            "dynamic_variables": dynamic_variables,
            "to_number": to_number,
        },
        ensure_ascii=False,
    )


def cache_call_context_sync(
    run_id: str,
    voice_config: VoiceCallConfig,
    dynamic_variables: dict[str, str],
    to_number: str,
) -> None:
    redis_client_sync.setex(
        _key(run_id),
        _CACHE_TTL_SECONDS,
        _encode(voice_config, dynamic_variables, to_number),
    )


def get_call_context_sync(run_id: str) -> dict[str, Any] | None:
    raw = redis_client_sync.get(_key(run_id))
    return json.loads(raw) if raw else None


async def get_call_context(run_id: str) -> dict[str, Any] | None:
    raw = await redis_client.get(_key(run_id))
    return json.loads(raw) if raw else None


def voice_config_from_context(context: dict[str, Any]) -> VoiceCallConfig:
    return VoiceCallConfig(**context["voice_config"])


def delete_call_context_sync(run_id: str) -> None:
    redis_client_sync.delete(_key(run_id))
