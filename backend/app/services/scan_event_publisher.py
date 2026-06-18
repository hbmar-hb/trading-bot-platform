"""Publisher for live AI scanner events.

Events are:
1. Broadcast in real time via Redis pub/sub (channel: ai_scan_updates).
2. Persisted in Redis list "ai_scan_events" for 24 hours so the frontend can
   retrieve recent history when the user opens the live tab.

Both sync (Celery) and async (FastAPI) publishers are provided.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.cache import _sign_message, sync_redis

CHANNEL = "ai_scan_updates"
EVENTS_LIST = "ai_scan_events"
_EVENTS_MAX_LEN = 5000          # hard cap on the Redis list
_EVENTS_TTL_SECONDS = 24 * 3600  # 24 hours


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_payload(
    *,
    source: str,
    scan_id: str,
    symbol: str,
    timeframe: str,
    status: str,
    direction: str | None = None,
    score: float | None = None,
    confidence: str | None = None,
    quality_tier: str | None = None,
    anti_fake_status: str | None = None,
    success_probability: float | None = None,
    regime: str | None = None,
    regime_confidence: float | None = None,
    rejection_reason: str | None = None,
    rejection_context: dict[str, Any] | None = None,
    features_preview: dict[str, Any] | None = None,
    scanned_at: datetime | None = None,
    message: str | None = None,
) -> dict:
    return {
        "type": "ai_scan_update",
        "source": source,
        "scan_id": scan_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "status": status,
        "direction": direction,
        "score": round(score, 2) if score is not None else None,
        "confidence": confidence,
        "quality_tier": quality_tier,
        "anti_fake_status": anti_fake_status,
        "success_probability": round(success_probability, 4) if success_probability is not None else None,
        "regime": regime,
        "regime_confidence": round(regime_confidence, 4) if regime_confidence is not None else None,
        "rejection_reason": rejection_reason,
        "rejection_context": rejection_context or {},
        "features_preview": features_preview or {},
        "scanned_at": (scanned_at or datetime.now(timezone.utc)).isoformat(),
        "message": message,
    }


def publish_scan_event_sync(
    *,
    source: str,
    scan_id: str,
    symbol: str,
    timeframe: str,
    status: str,
    direction: str | None = None,
    score: float | None = None,
    confidence: str | None = None,
    quality_tier: str | None = None,
    anti_fake_status: str | None = None,
    success_probability: float | None = None,
    regime: str | None = None,
    regime_confidence: float | None = None,
    rejection_reason: str | None = None,
    rejection_context: dict[str, Any] | None = None,
    features_preview: dict[str, Any] | None = None,
    scanned_at: datetime | None = None,
    message: str | None = None,
) -> None:
    """Publish a scan event from a synchronous context (Celery worker)."""
    try:
        payload = _build_payload(
            source=source,
            scan_id=scan_id,
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            direction=direction,
            score=score,
            confidence=confidence,
            quality_tier=quality_tier,
            anti_fake_status=anti_fake_status,
            success_probability=success_probability,
            regime=regime,
            regime_confidence=regime_confidence,
            rejection_reason=rejection_reason,
            rejection_context=rejection_context,
            features_preview=features_preview,
            scanned_at=scanned_at,
            message=message,
        )
        payload["sig"] = _sign_message(payload)
        data = json.dumps(payload, default=str)

        # Real-time broadcast
        sync_redis.publish(CHANNEL, data)
        # 24-hour durable history
        sync_redis.lpush(EVENTS_LIST, data)
        sync_redis.ltrim(EVENTS_LIST, 0, _EVENTS_MAX_LEN - 1)
        sync_redis.expire(EVENTS_LIST, _EVENTS_TTL_SECONDS)
    except Exception:
        # Never let telemetry break the scanner
        pass


async def publish_scan_event_async(
    *,
    source: str,
    scan_id: str,
    symbol: str,
    timeframe: str,
    status: str,
    direction: str | None = None,
    score: float | None = None,
    confidence: str | None = None,
    quality_tier: str | None = None,
    anti_fake_status: str | None = None,
    success_probability: float | None = None,
    regime: str | None = None,
    regime_confidence: float | None = None,
    rejection_reason: str | None = None,
    rejection_context: dict[str, Any] | None = None,
    features_preview: dict[str, Any] | None = None,
    scanned_at: datetime | None = None,
    message: str | None = None,
) -> None:
    """Publish a scan event from an async context (FastAPI endpoint)."""
    import redis.asyncio as aioredis
    from config.settings import settings

    try:
        payload = _build_payload(
            source=source,
            scan_id=scan_id,
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            direction=direction,
            score=score,
            confidence=confidence,
            quality_tier=quality_tier,
            anti_fake_status=anti_fake_status,
            success_probability=success_probability,
            regime=regime,
            regime_confidence=regime_confidence,
            rejection_reason=rejection_reason,
            rejection_context=rejection_context,
            features_preview=features_preview,
            scanned_at=scanned_at,
            message=message,
        )
        payload["sig"] = _sign_message(payload)
        data = json.dumps(payload, default=str)

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await r.publish(CHANNEL, data)
            await r.lpush(EVENTS_LIST, data)
            await r.ltrim(EVENTS_LIST, 0, _EVENTS_MAX_LEN - 1)
            await r.expire(EVENTS_LIST, _EVENTS_TTL_SECONDS)
        finally:
            await r.aclose()
    except Exception:
        pass


def get_recent_scan_events(count: int = 500) -> list[dict]:
    """Return the last `count` persisted scan events (sync, for HTTP endpoint)."""
    try:
        items = sync_redis.lrange(EVENTS_LIST, 0, count - 1)
        events = []
        for item in items:
            try:
                events.append(json.loads(item))
            except Exception:
                continue
        # Redis returns newest first; reverse to chronological order
        events.reverse()
        return events
    except Exception:
        return []


def new_scan_id() -> str:
    return str(uuid.uuid4())
