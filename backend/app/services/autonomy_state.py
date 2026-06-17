"""Autonomy state helpers — precedence-aware pause/resume coordination.

Precedence (highest → lowest):
  kill_switch = emergency_stop > deployment_gate > drift > exchange_health > drawdown > optimizer_error = optimizer_conflict
"""
from __future__ import annotations

from datetime import datetime, timezone

_AUTONOMY_PRECEDENCE: dict[str, int] = {
    "kill_switch": 100,
    "emergency_stop": 100,
    "deployment_gate": 80,
    "drift": 60,
    "exchange_health": 40,
    "drawdown": 20,
    "optimizer_error": 10,
    "optimizer_conflict": 10,
}


def _current_precedence(autonomy: dict) -> int:
    return _AUTONOMY_PRECEDENCE.get(autonomy.get("paused_by"), 0)


def can_pause(autonomy: dict, reason: str) -> bool:
    """Return True if `reason` may overwrite the current paused_by."""
    return _AUTONOMY_PRECEDENCE.get(reason, 0) >= _current_precedence(autonomy)


def can_resume(autonomy: dict, reason: str) -> bool:
    """Return True if the bot was paused by `reason` and no higher system took over."""
    return autonomy.get("paused_by") == reason


def mark_paused(autonomy: dict, reason: str) -> bool:
    """Set paused_by if precedence allows. Returns True if written."""
    if can_pause(autonomy, reason):
        autonomy["paused_by"] = reason
        autonomy["paused_at"] = datetime.now(timezone.utc).isoformat()
        return True
    return False


def clear_pause(autonomy: dict, reason: str) -> bool:
    """Clear paused_by keys if the bot is currently paused by `reason`."""
    if can_resume(autonomy, reason):
        autonomy.pop("paused_by", None)
        autonomy.pop("paused_at", None)
        autonomy.pop("auto_resume_after", None)
        return True
    return False
