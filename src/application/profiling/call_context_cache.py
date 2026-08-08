"""Contexto de llamada preparado antes de que el candidato conteste."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, cast

from src.application.profiling.voice_config_resolver import VoiceCallConfig
from src.infrastructure.cache.redis_client import redis_client, redis_client_sync

_CACHE_PREFIX = "profiling:call-context:"
_ACTIVE_CALL_PREFIX = "profiling:active-call:"
_TWIML_PREFIX = "profiling:prepared-twiml:"
_CACHE_TTL_SECONDS = 900


def build_dynamic_variables(candidate_name: str, job_title: str, process_id: str) -> dict[str, str]:
    return {"candidate_name": candidate_name, "job_title": job_title, "process_id": process_id}


def _key(run_id: str) -> str:
    return f"{_CACHE_PREFIX}{run_id}"


def _active_call_key(run_id: str) -> str:
    return f"{_ACTIVE_CALL_PREFIX}{run_id}"


def _twiml_key(run_id: str, call_sid: str) -> str:
    return f"{_TWIML_PREFIX}{run_id}:{call_sid}"


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
    raw = cast(str | bytes | None, redis_client_sync.get(_key(run_id)))
    if not raw:
        return None
    decoded = json.loads(raw)
    return cast(dict[str, Any], decoded) if isinstance(decoded, dict) else None


async def get_call_context(run_id: str) -> dict[str, Any] | None:
    raw = await redis_client.get(_key(run_id))
    return json.loads(raw) if raw else None


def voice_config_from_context(context: dict[str, Any]) -> VoiceCallConfig:
    return VoiceCallConfig(**context["voice_config"])


def cache_prepared_twiml_sync(run_id: str, call_sid: str, twiml: str) -> None:
    """Publica atomica y temporalmente el TwiML del intento activo."""
    with redis_client_sync.pipeline(transaction=True) as pipe:
        pipe.setex(_active_call_key(run_id), _CACHE_TTL_SECONDS, call_sid)
        pipe.setex(_twiml_key(run_id, call_sid), _CACHE_TTL_SECONDS, twiml)
        pipe.execute()


async def get_prepared_twiml(run_id: str, call_sid: str) -> str | None:
    """Solo retorna TwiML si el callback pertenece al intento activo."""
    async with redis_client.pipeline(transaction=False) as pipe:
        pipe.get(_active_call_key(run_id))
        pipe.get(_twiml_key(run_id, call_sid))
        active_sid, twiml = await pipe.execute()
    return twiml if active_sid == call_sid else None


def delete_call_context_sync(run_id: str) -> None:
    keys = [_key(run_id), _active_call_key(run_id)]
    keys.extend(redis_client_sync.scan_iter(match=f"{_TWIML_PREFIX}{run_id}:*", count=10))
    redis_client_sync.delete(*keys)
