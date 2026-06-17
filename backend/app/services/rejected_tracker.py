"""Rejected Signals Tracker — persists rejected signals for survival-bias auditing.

Every rejection point in bot_activator.py should call `record_rejection()`
to create an AISignalRejected row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.models.ai_signal_rejected import AISignalRejected


# List of valid rejection reasons
VALID_REASONS = frozenset([
    "stale", "tier", "status", "score", "concurrent",
    "stacking", "slippage", "macro", "regime",
    "drift", "kelly", "portfolio", "look_ahead",
    "wf_rejected", "optimal_config_missing",
    "paper_divergence", "oi_cvd", "session_funding", "rolling_beta",
    "circuit_breaker", "same_side",
    "fundamental", "cost_gate", "exposure_cap",
    "llm_block", "llm_caution", "longevity",
    "symbol_deployment_gate", "prob_threshold",
    "montecarlo",
])


def record_rejection(
    db,
    signal,
    reason: str,
    bot_id: str | None = None,
    extra_context: dict | None = None,
    trigger_diagnosis: bool = False,
) -> AISignalRejected | None:
    """Persist a rejected signal to the audit table.

    Args:
        db: SQLAlchemy session
        signal: AISignal instance or duck-typed object
        reason: rejection reason (must be in VALID_REASONS)
        bot_id: optional bot UUID string
        extra_context: additional JSON data to merge into features_snapshot

    Returns:
        The created AISignalRejected row, or None if signal is None.
    """
    if signal is None:
        return None

    if reason not in VALID_REASONS:
        logger.warning(f"[REJECTED] Unknown rejection reason: {reason}")
        reason = "unknown"

    snapshot = dict(signal.features) if signal.features else {}
    if extra_context:
        snapshot = {**snapshot, **extra_context}

    row = AISignalRejected(
        ticker=signal.ticker,
        timeframe=signal.timeframe,
        direction=signal.direction,
        score=signal.score or 0.0,
        quality_tier=signal.quality_tier,
        anti_fake_status=signal.anti_fake_status,
        rejection_reason=reason,
        features_snapshot=snapshot,
        bot_id=bot_id,
        signal_time=signal.signal_time,
    )
    db.add(row)
    db.commit()

    logger.info(
        f"[REJECTED] {signal.ticker}/{signal.timeframe} {signal.direction} "
        f"score={signal.score} reason={reason} bot={bot_id}"
    )

    if trigger_diagnosis and signal and hasattr(signal, "id"):
        try:
            # Rate-limit: only BLOCK/CAUTION signals are worth diagnosing
            if getattr(signal, "anti_fake_status", None) not in ("BLOCK", "CAUTION"):
                pass  # skip silently
            else:
                # Only trigger LLM diagnosis if bot belongs to an admin user
                should_diagnose = False
                if bot_id:
                    from app.services.database import SessionLocal
                    from app.models.bot_config import BotConfig
                    from app.models.user import User
                    with SessionLocal() as check_db:
                        bot = check_db.get(BotConfig, bot_id)
                        if bot and bot.user_id:
                            user = check_db.get(User, bot.user_id)
                            if user and user.role == "admin":
                                should_diagnose = True
                # Deduplicate: max 1 diagnosis per (ticker, reason, bot_id) every 6h
                if should_diagnose:
                    from app.services.cache import sync_redis
                    dedup_key = f"llm_diag_dedup:{signal.ticker}:{reason}:{bot_id}"
                    # setnx with 6h TTL — returns True only if key did not exist
                    is_new = sync_redis.set(dedup_key, "1", nx=True, ex=21600)
                    if is_new:
                        from app.tasks.llm_tasks import generate_signal_diagnosis
                        gate_details = {"reason": reason, "bot_id": bot_id}
                        if extra_context:
                            gate_details.update(extra_context)
                        generate_signal_diagnosis.delay(
                            str(signal.id),
                            f"gate_{reason}" if reason in VALID_REASONS else "gate_unknown",
                            gate_details=gate_details,
                        )
                        logger.info(f"[REJECTED] Queued LLM diagnosis for {signal.ticker}/{reason}")
                    else:
                        logger.debug(
                            f"[REJECTED] Skipped duplicate LLM diagnosis for "
                            f"{signal.ticker}/{reason}/{bot_id}"
                        )
        except Exception as diag_exc:
            logger.debug(f"[REJECTED] Failed to trigger LLM diagnosis: {diag_exc}")

    return row


def get_rejected_summary(db, days: int = 30) -> dict[str, Any]:
    """Return summary of rejected signals by reason.

    Returns dict:
        {
            "total": int,
            "by_reason": {reason: {"count": int, "would_win_pct": float|None}},
            "top_filters": list[str],  # reasons with highest would_win_pct
        }
    """
    from sqlalchemy import func

    since = datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)

    from sqlalchemy import case

    rows = (
        db.query(
            AISignalRejected.rejection_reason,
            func.count().label("count"),
            func.sum(
                case((AISignalRejected.would_have_been_winner.is_(True), 1), else_=0)
            ).label("wins"),
            func.sum(
                case((AISignalRejected.would_have_been_winner.isnot(None), 1), else_=0)
            ).label("audited"),
        )
        .filter(AISignalRejected.rejected_at >= since)
        .group_by(AISignalRejected.rejection_reason)
        .all()
    )

    by_reason = {}
    for reason, count, wins, audited in rows:
        win_pct = round(wins / audited * 100, 1) if audited and audited > 0 else None
        by_reason[reason] = {"count": count, "would_win_pct": win_pct}

    total = sum(r["count"] for r in by_reason.values())

    # Top filters: reasons with >60% would_win_pct (overly aggressive)
    top_filters = [
        r for r, data in by_reason.items()
        if data["would_win_pct"] is not None and data["would_win_pct"] > 60
    ]

    return {
        "total": total,
        "by_reason": by_reason,
        "top_filters": top_filters,
        "days": days,
    }


async def get_rejected_summary_by_ticker_async(db, ticker: str, days: int = 30) -> dict[str, Any]:
    """Async version: rejection summary for a specific ticker."""
    from sqlalchemy import case, func, select

    since = datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)

    stmt = (
        select(
            AISignalRejected.rejection_reason,
            func.count().label("count"),
            func.sum(
                case((AISignalRejected.would_have_been_winner.is_(True), 1), else_=0)
            ).label("wins"),
            func.sum(
                case((AISignalRejected.would_have_been_winner.isnot(None), 1), else_=0)
            ).label("audited"),
        )
        .where(
            AISignalRejected.ticker == ticker,
            AISignalRejected.rejected_at >= since,
        )
        .group_by(AISignalRejected.rejection_reason)
    )

    result = await db.execute(stmt)
    rows = result.all()

    by_reason = {}
    for reason, count, wins, audited in rows:
        win_pct = round(wins / audited * 100, 1) if audited and audited > 0 else None
        by_reason[reason] = {"count": count, "would_win_pct": win_pct}

    total = sum(r["count"] for r in by_reason.values())

    top_filters = [
        r for r, data in by_reason.items()
        if data["would_win_pct"] is not None and data["would_win_pct"] > 60
    ]

    return {
        "total": total,
        "by_reason": by_reason,
        "top_filters": top_filters,
        "days": days,
    }


async def get_rejected_by_ticker_async(
    db,
    ticker: str,
    days: int = 30,
    timeframe: str | None = None,
    reason: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Async version: paginated list of rejected signals for a specific ticker."""
    from sqlalchemy import func, select

    since = datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)

    # Count query
    count_stmt = select(func.count()).select_from(AISignalRejected).where(
        AISignalRejected.ticker == ticker,
        AISignalRejected.rejected_at >= since,
    )
    if timeframe:
        count_stmt = count_stmt.where(AISignalRejected.timeframe == timeframe)
    if reason:
        count_stmt = count_stmt.where(AISignalRejected.rejection_reason == reason)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Data query
    stmt = select(AISignalRejected).where(
        AISignalRejected.ticker == ticker,
        AISignalRejected.rejected_at >= since,
    )
    if timeframe:
        stmt = stmt.where(AISignalRejected.timeframe == timeframe)
    if reason:
        stmt = stmt.where(AISignalRejected.rejection_reason == reason)

    stmt = stmt.order_by(AISignalRejected.rejected_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = [
        {
            "id": str(r.id),
            "ticker": r.ticker,
            "timeframe": r.timeframe,
            "direction": r.direction,
            "score": r.score,
            "quality_tier": r.quality_tier,
            "anti_fake_status": r.anti_fake_status,
            "rejection_reason": r.rejection_reason,
            "features_snapshot": r.features_snapshot,
            "bot_id": r.bot_id,
            "signal_time": r.signal_time.isoformat() if r.signal_time else None,
            "rejected_at": r.rejected_at.isoformat() if r.rejected_at else None,
            "would_have_been_winner": r.would_have_been_winner,
            "similar_signal_outcome": r.similar_signal_outcome,
            "similar_signal_pnl_pct": r.similar_signal_pnl_pct,
        }
        for r in rows
    ]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }
