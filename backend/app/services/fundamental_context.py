"""Fundamental Context Service — CFTC CoT, token unlocks, macro events.

Provides fundamental analysis as a pre-trade gate.
Architecture: pluggable providers (CFTC, TokenUnlocks, Macro) with
DB caching and admin manual override support.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select, desc
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.services.database import AsyncSessionLocal
from app.models.fundamental_snapshot import FundamentalSnapshot


_CACHE_TTL_HOURS = 6

# ── Provider interface ───────────────────────────────────────────────────────

async def _fetch_cftc_cot(ticker: str) -> dict | None:
    """Fetch CFTC Commitment of Traders data for BTC/ETH futures.
    Returns None if unavailable or ticker not supported.
    """
    # TODO: integrate with Coinglass / Bybt API when API key available
    # For now, return None so the gate falls back to neutral
    base = ticker.replace("USDT", "").replace("USD", "").replace("/", "").split(":")[0]
    if base not in ("BTC", "ETH"):
        return None
    return None


async def _fetch_token_unlocks(ticker: str) -> dict | None:
    """Fetch upcoming token unlock events.
    Returns None if unavailable.
    """
    # TODO: integrate with token.unlocks API when key available
    return None


async def _fetch_macro_events(ticker: str) -> dict | None:
    """Fetch macro events from existing macro_context service."""
    try:
        from app.services.macro_context import get_macro_context
        ctx = get_macro_context(ticker)
        if ctx.get("high_impact_soon"):
            return {
                "high_impact_events": ctx["high_impact_soon"],
                "recommendation": ctx.get("recommendation", "proceed"),
            }
    except Exception as exc:
        logger.warning(f"[FundamentalContext] Macro fetch failed: {exc}")
    return None


# ── Cache layer ──────────────────────────────────────────────────────────────

async def _get_cached(ticker: str, source: str) -> FundamentalSnapshot | None:
    """Return cached snapshot if still valid."""
    now = datetime.now(timezone.utc)
    stale = now - timedelta(hours=_CACHE_TTL_HOURS)
    async with AsyncSessionLocal() as db:
        stmt = select(FundamentalSnapshot).where(
            FundamentalSnapshot.ticker == ticker.upper(),
            FundamentalSnapshot.source == source,
            FundamentalSnapshot.fetched_at >= stale,
        ).order_by(desc(FundamentalSnapshot.fetched_at)).limit(1)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


async def _upsert_snapshot(
    ticker: str,
    source: str,
    data: dict,
    signal: str = "NEUTRAL",
    confidence: float = 0.5,
    valid_until: datetime | None = None,
) -> FundamentalSnapshot:
    """Upsert a fundamental snapshot."""
    now = datetime.now(timezone.utc)
    values = {
        "ticker": ticker.upper(),
        "source": source,
        "data": data,
        "signal": signal,
        "confidence": confidence,
        "valid_until": valid_until,
        "fetched_at": now,
    }
    stmt = (
        pg_insert(FundamentalSnapshot)
        .values(**values)
        .on_conflict_do_nothing()
    )
    async with AsyncSessionLocal() as db:
        await db.execute(stmt)
        await db.commit()
        # Return the inserted row
        result = await db.execute(
            select(FundamentalSnapshot).where(
                FundamentalSnapshot.ticker == ticker.upper(),
                FundamentalSnapshot.source == source,
            ).order_by(desc(FundamentalSnapshot.fetched_at)).limit(1)
        )
        return result.scalar_one()


# ── Public API ───────────────────────────────────────────────────────────────

async def get_fundamental_context(ticker: str) -> dict[str, Any]:
    """Return aggregated fundamental context for a ticker.

    Queries all providers + manual events and returns the most restrictive signal.
    """
    ticker = ticker.upper()

    # 1. Fetch all cached snapshots for this ticker (including manual events)
    now = datetime.now(timezone.utc)
    stale = now - timedelta(hours=_CACHE_TTL_HOURS)
    results = []

    async with AsyncSessionLocal() as db:
        stmt = select(FundamentalSnapshot).where(
            FundamentalSnapshot.ticker == ticker,
            FundamentalSnapshot.fetched_at >= stale,
        ).order_by(desc(FundamentalSnapshot.fetched_at))
        rows = (await db.execute(stmt)).scalars().all()
        for row in rows:
            results.append({
                "source": row.source,
                "signal": row.signal,
                "confidence": row.confidence,
                "data": row.data,
                "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
            })

    # 2. Auto-fetch from external providers if not cached
    auto_sources = {
        "cot": _fetch_cftc_cot,
        "token_unlock": _fetch_token_unlocks,
        "macro": _fetch_macro_events,
    }
    cached_sources = {r["source"] for r in results}
    for source, fetcher in auto_sources.items():
        if source in cached_sources:
            continue
        try:
            data = await fetcher(ticker)
            if data:
                signal, confidence = _compute_signal(source, data)
                snap = await _upsert_snapshot(ticker, source, data, signal, confidence)
                results.append({
                    "source": source,
                    "signal": signal,
                    "confidence": confidence,
                    "data": data,
                    "fetched_at": snap.fetched_at.isoformat(),
                })
        except Exception as exc:
            logger.warning(f"[FundamentalContext] {source} fetch failed for {ticker}: {exc}")

    # Aggregate: most restrictive wins
    priority = {"BLOCK": 3, "CAUTION": 2, "NEUTRAL": 1, "FAVORABLE": 0}
    overall_signal = "NEUTRAL"
    overall_confidence = 0.0
    for r in results:
        if priority.get(r["signal"], 0) > priority.get(overall_signal, 0):
            overall_signal = r["signal"]
            overall_confidence = r["confidence"]

    return {
        "ticker": ticker,
        "overall_signal": overall_signal,
        "overall_confidence": overall_confidence,
        "sources": results,
        "note": (
            "Fundamental data is limited without third-party API keys. "
            "Admins can upload manual events via POST /ai/fundamentals/manual."
        ),
    }


def _compute_signal(source: str, data: dict) -> tuple[str, float]:
    """Compute signal from raw provider data."""
    if source == "cot":
        # Institutional net long ratio
        net_long_ratio = data.get("net_long_ratio", 0.5)
        if net_long_ratio > 0.8:
            return "CAUTION", 0.6
        if net_long_ratio < 0.2:
            return "CAUTION", 0.6
        return "NEUTRAL", 0.5

    if source == "token_unlock":
        unlocks = data.get("upcoming_unlocks", [])
        total_pct = sum(u.get("percent", 0) for u in unlocks)
        if total_pct > 10:
            return "BLOCK", 0.85
        if total_pct > 5:
            return "CAUTION", 0.7
        return "NEUTRAL", 0.5

    if source == "macro":
        events = data.get("high_impact_events", [])
        if events:
            return "CAUTION", 0.6
        return "NEUTRAL", 0.5

    return "NEUTRAL", 0.5


async def check_fundamental_gate(
    ticker: str,
    sensitivity: str = "normal",
) -> tuple[bool, str, str, float]:
    """Return (allowed, reason, signal, confidence).

    Sensitivity:
      strict  → CAUTION blocks, BLOCK blocks
      normal  → BLOCK blocks, CAUTION warns
      relaxed → only BLOCK blocks
    """
    ctx = await get_fundamental_context(ticker)
    signal = ctx["overall_signal"]
    confidence = ctx["overall_confidence"]

    if signal == "BLOCK":
        return False, f"Fundamental gate: {signal} (confidence={confidence:.0%})", signal, confidence

    if signal == "CAUTION" and sensitivity in ("strict", "normal"):
        if sensitivity == "strict":
            return False, f"Fundamental gate (strict): {signal} (confidence={confidence:.0%})", signal, confidence
        return True, f"Fundamental caution (normal): {signal} (confidence={confidence:.0%})", signal, confidence

    return True, "", signal, confidence


# ── Admin manual upload ──────────────────────────────────────────────────────

async def upload_manual_event(
    ticker: str,
    source: str,
    data: dict,
    signal: str,
    confidence: float,
    valid_hours: int = 48,
) -> FundamentalSnapshot:
    """Allow admins to manually upload fundamental events."""
    valid_until = datetime.now(timezone.utc) + timedelta(hours=valid_hours)
    return await _upsert_snapshot(ticker, source, data, signal, confidence, valid_until)
