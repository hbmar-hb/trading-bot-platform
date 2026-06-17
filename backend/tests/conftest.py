"""Shared test fixtures for the backend test suite."""
from __future__ import annotations

import pytest


class FakeRedis:
    """In-memory Redis substitute for unit tests.

    Supports only the subset of Redis list operations used by the shadow-mode
    modules so that tests do not depend on a real Redis instance.
    """

    def __init__(self):
        self._data: dict[str, list[str]] = {}

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = self._data.get(key, [])
        if end == -1:
            return lst[start:]
        return lst[start : end + 1]

    def rpush(self, key: str, *values: str) -> int:
        self._data.setdefault(key, []).extend(values)
        return len(self._data[key])

    def delete(self, key: str) -> int:
        return 1 if self._data.pop(key, None) is not None else 0

    def expire(self, key: str, ttl: int) -> bool:
        return True

    def llen(self, key: str) -> int:
        return len(self._data.get(key, []))


@pytest.fixture
def fake_redis(monkeypatch):
    """Replace the production Redis client used by shadow-mode modules."""
    fake = FakeRedis()
    monkeypatch.setattr("ai.services.candidate_shadow_mode.sync_redis", fake)
    monkeypatch.setattr("ai.services.shadow_mode.sync_redis", fake)
    return fake


@pytest.fixture
def event_loop(event_loop):
    """Override pytest-asyncio's default loop to keep it explicit."""
    return event_loop
