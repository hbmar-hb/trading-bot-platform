"""Confirmation Entry scanner — SMC-style CDC verification in Lower Time Frames.

When the main scanner (15m/1h) finds a valid setup but the LTF (5m) has not
yet confirmed a Change of Character (CHoCH), the setup is placed on a Redis
watchlist. A background task polls the watchlist every few minutes and
promotes it to a real AISignal once CDC is confirmed.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from loguru import logger

from app.core.ict_engine import analyze as ict_analyze
from app.core.constants import cdc_for
from app.services.ai_scanner import fetch_ohlcv

# Redis key prefix for SMC watchlist
_WATCH_PREFIX = "smc_watch"
_WATCH_TTL_S = 1800  # 30 minutes


def _watch_key(symbol: str, direction: str, timeframe: str) -> str:
    return f"{_WATCH_PREFIX}:{symbol}:{timeframe}:{direction}"


def add_to_watchlist(
    redis_client,
    symbol: str,
    direction: str,
    timeframe: str,
    poi_price: float,
    score: float,
    quality_tier: str | None,
) -> None:
    """Store a pending setup in Redis watchlist."""
    key = _watch_key(symbol, direction, timeframe)
    data = {
        "symbol": symbol,
        "direction": direction,
        "timeframe": timeframe,
        "poi_price": poi_price,
        "score": score,
        "quality_tier": quality_tier,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    redis_client.setex(key, _WATCH_TTL_S, json.dumps(data))
    logger.info(f"[CONFIRMATION] {symbol}/{timeframe} {direction} added to watchlist @ {poi_price}")


def remove_from_watchlist(redis_client, symbol: str, direction: str, timeframe: str = "") -> None:
    """Remove a setup from the Redis watchlist.
    
    If timeframe is not provided, attempts to delete the legacy key format
    for backwards compatibility.
    """
    if timeframe:
        key = _watch_key(symbol, direction, timeframe)
    else:
        key = f"{_WATCH_PREFIX}:{symbol}:{direction}"
    redis_client.delete(key)


def get_watchlist(redis_client) -> list[dict]:
    """Return all pending setups from Redis."""
    keys = redis_client.keys(f"{_WATCH_PREFIX}:*")
    items = []
    for key in keys:
        raw = redis_client.get(key)
        if raw:
            try:
                data = json.loads(raw)
                # Backwards compat: old keys had no timeframe in key
                if "timeframe" not in data:
                    data["timeframe"] = "1h"
                items.append(data)
            except Exception:
                pass
    return items


def check_ltf_cdc(ltf_ohlcv: list, direction: str) -> bool:
    """Verify if the LTF (e.g. 5m) shows a Change of Character confirming the setup.

    Args:
        ltf_ohlcv: CCXT-format OHLCV list from the lower timeframe.
        direction: "long" or "short" — the expected direction of the trade.

    Returns:
        True when the LTF shows a CHoCH in the setup's direction.
    """
    if not ltf_ohlcv or len(ltf_ohlcv) < 30:
        return False

    closed = [
        {"open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
        for c in ltf_ohlcv[:-1]
    ]
    ict = ict_analyze(closed)

    if ict.last_break is None:
        return False

    # For a LONG setup we want CHoCH bear→bull (price breaks above a swing high
    # while previous bias was bearish) OR a BOS in bull bias.
    # For a SHORT setup we want CHoCH bull→bear.
    break_kind = ict.last_break.kind       # "BOS" | "CHoCH"
    break_dir = ict.last_break.direction   # "bull" | "bear"

    if direction == "long":
        # Confirming break to the upside
        if break_dir == "bull" and break_kind in ("BOS", "CHoCH"):
            return True
    else:  # short
        # Confirming break to the downside
        if break_dir == "bear" and break_kind in ("BOS", "CHoCH"):
            return True

    return False


async def verify_and_promote(
    redis_client,
    symbol: str,
    direction: str,
    timeframe: str,
    cdc_timeframe: str | None = None,
) -> dict | None:
    """Fetch LTF data, verify CDC, and return updated OHLCV if confirmed.

    Args:
        cdc_timeframe: override for the confirmation TF. If None, uses CDC_MAP.

    Returns the LTF OHLCV list when CDC is confirmed, otherwise None.
    """
    ltf_tf = cdc_timeframe or cdc_for(timeframe) or "5m"
    _, ltf_ohlcv = await fetch_ohlcv(symbol, ltf_tf)
    if not ltf_ohlcv or len(ltf_ohlcv) < 30:
        logger.debug(f"[CONFIRMATION] {symbol}: insufficient LTF data")
        return None

    confirmed = check_ltf_cdc(ltf_ohlcv, direction)
    if confirmed:
        logger.info(f"[CONFIRMATION] {symbol}/{timeframe} {direction}: CDC confirmed in {ltf_tf}")
        return ltf_ohlcv

    logger.debug(f"[CONFIRMATION] {symbol}/{timeframe} {direction}: no CDC yet")
    return None
