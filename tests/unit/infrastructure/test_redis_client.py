from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import redis

from src.infrastructure.cache import redis_client as module


def test_sync_cache_read_timeout_falls_back_to_database() -> None:
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(
        model_name="gpt-4o"
    )

    with (
        patch.object(
            module.redis_client_sync,
            "get",
            side_effect=redis.TimeoutError("cache unavailable"),
        ),
        patch.object(
            module.redis_client_sync,
            "setex",
            side_effect=redis.TimeoutError("cache unavailable"),
        ),
    ):
        model = module.get_active_ai_model_sync(
            db, "VOICE_PROFILING", "OPENAI", "fallback"
        )

    assert model == "gpt-4o"
    db.execute.assert_called_once()


def test_sync_cache_helpers_do_not_propagate_redis_errors() -> None:
    with patch.object(
        module.redis_client_sync,
        "get",
        side_effect=redis.ConnectionError("offline"),
    ):
        assert module._get_cached_sync("key") is None

    with patch.object(
        module.redis_client_sync,
        "setex",
        side_effect=redis.ConnectionError("offline"),
    ):
        module._set_cached_sync("key", "value")
