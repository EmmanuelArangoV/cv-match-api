from __future__ import annotations

import pytest

from src.application.profiling import call_context_cache


class _SyncPipeline:
    def __init__(self, data: dict[str, str]) -> None:
        self.data = data
        self.pending: list[tuple[str, str]] = []

    def __enter__(self) -> _SyncPipeline:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def setex(self, key: str, _ttl: int, value: str) -> _SyncPipeline:
        self.pending.append((key, value))
        return self

    def execute(self) -> list[bool]:
        for key, value in self.pending:
            self.data[key] = value
        return [True] * len(self.pending)


class _SyncRedis:
    def __init__(self, data: dict[str, str]) -> None:
        self.data = data

    def pipeline(self, *, transaction: bool) -> _SyncPipeline:
        assert transaction is True
        return _SyncPipeline(self.data)


class _AsyncPipeline:
    def __init__(self, data: dict[str, str]) -> None:
        self.data = data
        self.keys: list[str] = []

    async def __aenter__(self) -> _AsyncPipeline:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def get(self, key: str) -> _AsyncPipeline:
        self.keys.append(key)
        return self

    async def execute(self) -> list[str | None]:
        return [self.data.get(key) for key in self.keys]


class _AsyncRedis:
    def __init__(self, data: dict[str, str]) -> None:
        self.data = data

    def pipeline(self, *, transaction: bool) -> _AsyncPipeline:
        assert transaction is False
        return _AsyncPipeline(self.data)


@pytest.mark.asyncio
async def test_prepared_twiml_is_only_returned_for_active_call_sid(monkeypatch) -> None:
    data: dict[str, str] = {}
    monkeypatch.setattr(call_context_cache, "redis_client_sync", _SyncRedis(data))
    monkeypatch.setattr(call_context_cache, "redis_client", _AsyncRedis(data))

    call_context_cache.cache_prepared_twiml_sync("run-1", "CA-new", "<Response/>")

    assert await call_context_cache.get_prepared_twiml("run-1", "CA-new") == "<Response/>"
    assert await call_context_cache.get_prepared_twiml("run-1", "CA-old") is None
