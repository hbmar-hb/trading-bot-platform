"""Signal Stacking Policy — prevents over-concentration in similar signals.

Rules:
  1. Max 2 open positions per (symbol, side, quality_tier, anti_fake_status) pattern
     within the same bot.
  2. Minimum 2-hour cooldown between stacked signals of the same pattern.
  3. Minimum 0.5% price distance between entry prices of stacked positions.

These limits are independent of max_concurrent (which is per-bot total).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import func

from app.models.position import Position


DEFAULT_MAX_STACK = 2
DEFAULT_COOLDOWN_MIN = 120
DEFAULT_MIN_PRICE_DISTANCE_PCT = 0.5


def check_stacking_policy(
    db,
    bot_id: str,
    symbol: str,
    side: str,
    quality_tier: str | None,
    anti_fake_status: str | None,
    entry_price: float,
    timeframe: str | None = None,
    max_stack: int = DEFAULT_MAX_STACK,
    cooldown_min: int = DEFAULT_COOLDOWN_MIN,
    min_price_distance_pct: float = DEFAULT_MIN_PRICE_DISTANCE_PCT,
) -> dict[str, Any]:
    """Evaluate whether a new signal violates the stacking policy.

    Returns:
        {"allowed": bool, "reason": str | None, "stack_count": int}
    """
    # Query open positions for this bot / symbol / side
    open_positions = (
        db.query(Position)
        .filter(
            Position.bot_id == bot_id,
            Position.symbol == symbol,
            Position.side == side,
            Position.status == "open",
        )
        .all()
    )

    # Filter by pattern (quality_tier + anti_fake_status)
    pattern_positions = []
    for pos in open_positions:
        meta = pos.extra_config or {}
        pos_tier = meta.get("quality_tier")
        pos_status = meta.get("anti_fake_status")
        if pos_tier == quality_tier and pos_status == anti_fake_status:
            pattern_positions.append(pos)

    stack_count = len(pattern_positions)

    # Rule 1: max stack per pattern
    if stack_count >= max_stack:
        reason = (
            f"stacking limit reached: {stack_count}/{max_stack} open positions "
            f"for {symbol} {side} {quality_tier}/{anti_fake_status}"
        )
        logger.info(f"[STACKING] {bot_id}: {reason}")
        return {"allowed": False, "reason": reason, "stack_count": stack_count}

    # Rule 2: cooldown between stacked signals
    if pattern_positions:
        most_recent = max(p.opened_at for p in pattern_positions)
        now = datetime.now(timezone.utc)
        if most_recent.tzinfo is None:
            most_recent = most_recent.replace(tzinfo=timezone.utc)
        elapsed_min = (now - most_recent).total_seconds() / 60
        if elapsed_min < cooldown_min:
            reason = (
                f"stacking cooldown active: {elapsed_min:.0f}min < {cooldown_min}min "
                f"since last {symbol} {side} {quality_tier}/{anti_fake_status}"
            )
            logger.info(f"[STACKING] {bot_id}: {reason}")
            return {"allowed": False, "reason": reason, "stack_count": stack_count}

    # Rule 3: minimum price distance between stacked entries
    if pattern_positions:
        for pos in pattern_positions:
            pos_price = float(pos.entry_price)
            if pos_price > 0 and entry_price > 0:
                distance_pct = abs(entry_price - pos_price) / pos_price * 100
                if distance_pct < min_price_distance_pct:
                    reason = (
                        f"stacking price distance too small: {distance_pct:.2f}% "
                        f"< {min_price_distance_pct}% vs existing entry {pos_price:.4f}"
                    )
                    logger.info(f"[STACKING] {bot_id}: {reason}")
                    return {"allowed": False, "reason": reason, "stack_count": stack_count}

    return {"allowed": True, "reason": None, "stack_count": stack_count}


def get_stacking_summary(db, bot_id: str) -> dict[str, Any]:
    """Return current stacking state for a bot."""
    open_positions = (
        db.query(Position)
        .filter(
            Position.bot_id == bot_id,
            Position.status == "open",
        )
        .all()
    )

    from collections import Counter
    patterns = Counter()
    for pos in open_positions:
        meta = pos.extra_config or {}
        key = f"{pos.symbol}:{pos.side}:{meta.get('quality_tier','?')}:{meta.get('anti_fake_status','?')}"
        patterns[key] += 1

    return {
        "total_open": len(open_positions),
        "by_pattern": dict(patterns),
    }
