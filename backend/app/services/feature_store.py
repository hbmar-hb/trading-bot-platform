"""
Feature Store — cache de features calculadas para evitar recomputación.

Mantiene en Redis un caché de features por (ticker, timeframe, timestamp).
TTL configurable (default 1h para features intraday, 1d para daily).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.services.cache import async_redis

# ── Constants ──────────────────────────────────────────────
DEFAULT_TTL_SECONDS = 3600  # 1 hour
FEATURE_PREFIX = "features:"


def _key(ticker: str, timeframe: str, timestamp: str) -> str:
    return f"{FEATURE_PREFIX}{ticker}:{timeframe}:{timestamp}"


async def get_features(ticker: str, timeframe: str, timestamp: str | None = None) -> dict | None:
    """Retrieve cached features for a signal."""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    key = _key(ticker, timeframe, ts)
    raw = await async_redis.get(key)
    if raw:
        return json.loads(raw)
    return None


async def set_features(
    ticker: str,
    timeframe: str,
    features: dict,
    timestamp: str | None = None,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> None:
    """Cache computed features."""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    key = _key(ticker, timeframe, ts)
    await async_redis.setex(key, ttl, json.dumps(features))


async def invalidate_features(ticker: str, timeframe: str) -> None:
    """Invalidate all cached features for a ticker/timeframe."""
    pattern = f"{FEATURE_PREFIX}{ticker}:{timeframe}:*"
    keys = await async_redis.keys(pattern)
    if keys:
        await async_redis.delete(*keys)
