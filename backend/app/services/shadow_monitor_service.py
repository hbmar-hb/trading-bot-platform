"""Shadow-mode monitoring service.

Provides the logic used by both the CLI monitor script and the admin system
page.  Runs a health check on the shadow-mode Redis keys and keeps a short
history of recent executions.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from ai.services.candidate_shadow_mode import CandidateShadowDeployer
from app.services.cache import sync_redis

CANDIDATE_KEY = "shadow_mode:candidate_predictions"
LIVE_KEY = "shadow_mode:predictions"
HISTORY_KEY = "shadow_monitor:history"
_HISTORY_MAX_ITEMS = 100
_HISTORY_TTL_SECONDS = int(timedelta(days=14).total_seconds())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_predictions(key: str, window_hours: int) -> list[dict[str, Any]]:
    cutoff = _now() - timedelta(hours=window_hours)
    items = sync_redis.lrange(key, 0, -1)
    parsed: list[dict[str, Any]] = []
    for raw in items:
        try:
            pred = json.loads(raw)
            ts = datetime.fromisoformat(pred["timestamp"])
            if ts >= cutoff:
                parsed.append(pred)
        except Exception:
            continue
    return parsed


def _analyze(
    key: str,
    preds: list[dict[str, Any]],
    none_lookback_hours: int,
    max_age_minutes: int,
) -> dict[str, Any]:
    now = _now()
    none_cutoff = now - timedelta(hours=none_lookback_hours)
    staleness_cutoff = now - timedelta(minutes=max_age_minutes)

    none_recent = [
        p for p in preds
        if p.get("signal_id") == "None"
        and datetime.fromisoformat(p["timestamp"]) >= none_cutoff
    ]

    recent = [
        p for p in preds
        if datetime.fromisoformat(p["timestamp"]) >= staleness_cutoff
    ]

    resolved = [p for p in preds if p.get("actual_outcome") is not None]

    return {
        "key": key,
        "total_in_window": len(preds),
        "resolved": len(resolved),
        "none_recent": len(none_recent),
        "recent_predictions": len(recent),
        "healthy_none": len(none_recent) == 0,
        "healthy_active": len(recent) > 0,
    }


def run_shadow_monitor_check(
    candidate_window_hours: int = 48,
    live_window_hours: int = 168,
    max_age_minutes: int = 60,
    max_none_lookback_hours: int = 24,
    save_history: bool = True,
) -> dict[str, Any]:
    """Run the shadow-mode health check and optionally persist the report."""
    candidate_preds = _load_predictions(CANDIDATE_KEY, candidate_window_hours)
    live_preds = _load_predictions(LIVE_KEY, live_window_hours)

    candidate_report = _analyze(
        CANDIDATE_KEY,
        candidate_preds,
        max_none_lookback_hours,
        max_age_minutes,
    )
    live_report = _analyze(
        LIVE_KEY,
        live_preds,
        max_none_lookback_hours,
        max_age_minutes,
    )

    healthy = (
        candidate_report["healthy_none"]
        and candidate_report["healthy_active"]
        and live_report["healthy_none"]
    )

    candidate_eval = CandidateShadowDeployer().evaluate_promotion()

    report = {
        "healthy": healthy,
        "candidate": candidate_report,
        "live": live_report,
        "candidate_eval": candidate_eval,
        "checked_at": _now().isoformat(),
    }

    if save_history:
        _save_history(report)

    return report


def _save_history(report: dict[str, Any]) -> None:
    try:
        sync_redis.lpush(HISTORY_KEY, json.dumps(report, default=str))
        sync_redis.ltrim(HISTORY_KEY, 0, _HISTORY_MAX_ITEMS - 1)
        sync_redis.expire(HISTORY_KEY, _HISTORY_TTL_SECONDS)
    except Exception as exc:
        logger.warning(f"[ShadowMonitor] Failed to save history: {exc}")


def get_shadow_monitor_history(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent shadow-mode check reports."""
    try:
        items = sync_redis.lrange(HISTORY_KEY, 0, limit - 1)
        return [json.loads(i) for i in items]
    except Exception as exc:
        logger.warning(f"[ShadowMonitor] Failed to read history: {exc}")
        return []
