"""Tier-based Circuit Breaker — auto-blocks AI tiers after N consecutive losses.

Runs every 15 minutes. For each active AI-signal bot:
  - Fetches recent closed AI positions grouped by quality_tier
  - If N consecutive losses for a tier, trips circuit breaker for that tier
  - Stores state in ai_signal_config['circuit_breaker_state'] without pausing the bot
  - Sends alert when a tier is blocked or unblocked

Auto-reactivation (regime-aware):
  - Bot-wide WR ≥ 50% in last 4h → unblock
  - Market regime changed since block → unblock (conditions are different)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger
from sqlalchemy import select, desc

from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal

_DEFAULT_THRESHOLDS = {
    "STRONG":   {"consecutive_sl": 3},
    "MODERATE": {"consecutive_sl": 2},
    "WEAK":     {"consecutive_sl": 2},
}

# Auto-reset circuit breaker after this many hours (legacy fallback)
_RESET_HOURS = 24

# Regime change auto-reset: if regime changes this much, reset breaker
_REGIME_CHANGE_RESET = True

# Only count SLs from the last N days — prevents stale historical losses from triggering CB
_RECENCY_DAYS = 7


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@shared_task(
    bind=True,
    max_retries=1,
    name="app.tasks.circuit_breaker_task.check_circuit_breakers",
    queue="default",
)
def check_circuit_breakers(self) -> dict:
    try:
        return _run_async(_check_async())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=120)


async def _check_async() -> dict:
    from app.models.bot_config import BotConfig
    from app.models.position import Position
    from app.services.notifier import notify_circuit_breaker

    notifications_by_bot: dict[str, dict] = {}

    def _queue_notification(bot_name: str, symbol: str, message: str) -> None:
        entry = notifications_by_bot.setdefault(bot_name, {"symbol": symbol, "messages": []})
        entry["messages"].append(message)

    async with AsyncSessionLocal() as db:
        bots = (
            await db.execute(
                select(BotConfig).where(
                    BotConfig.ai_signal_mode.is_(True),
                    BotConfig.status == "active",
                )
            )
        ).scalars().all()

        tripped, reset = 0, 0
        for bot in bots:
            cfg = dict(bot.ai_signal_config or {})
            thresholds = cfg.get("circuit_breaker_thresholds", _DEFAULT_THRESHOLDS)
            cb_state = dict(cfg.get("circuit_breaker_state", {}))

            # Auto-reset old trips
            for tier, state in list(cb_state.items()):
                tripped_at = state.get("tripped_at")
                if tripped_at:
                    try:
                        dt = datetime.fromisoformat(tripped_at)
                        if datetime.now(timezone.utc) - dt > timedelta(hours=_RESET_HOURS):
                            cb_state[tier] = {"consecutive_sl": 0, "tripped_at": None}
                            reset += 1
                            logger.info(
                                f"[CIRCUIT BREAKER] {bot.bot_name} tier {tier} auto-reset "
                                f"after {_RESET_HOURS}h"
                            )
                            _queue_notification(
                                bot.bot_name, bot.symbol,
                                f"Tier {tier} DESBLOQUEADO tras {_RESET_HOURS}h de bloqueo"
                            )
                    except Exception:
                        pass

            # Only count SLs within the recency window — stale historical losses must not
            # count as "consecutive". A WEAK SL from 13 days ago is not a current losing streak.
            recency_cutoff = datetime.now(timezone.utc) - timedelta(days=_RECENCY_DAYS)

            # Fetch recent closed AI positions within recency window
            positions = (
                await db.execute(
                    select(Position)
                    .where(
                        Position.bot_id == bot.id,
                        Position.status == "closed",
                        Position.source == "ai_bot",
                        Position.closed_at >= recency_cutoff,
                    )
                    .order_by(desc(Position.closed_at))
                    .limit(50)
                )
            ).scalars().all()

            # Only evaluate tiers that are currently allowed for this bot.
            # A WEAK SL should not trigger a block if WEAK signals can't even execute.
            allowed_tiers = set(cfg.get("allowed_tiers", ["STRONG", "MODERATE", "WEAK"]))

            # Group by tier and count consecutive losses from most recent
            tier_losses: dict[str, int] = {}
            for p in positions:
                tier = (p.extra_config or {}).get("quality_tier", "UNKNOWN")
                if tier not in allowed_tiers:
                    continue  # Skip tiers the bot can't trade — their SLs are irrelevant
                if tier not in tier_losses:
                    tier_losses[tier] = 0
                # Only count if we haven't seen a winner yet for this tier
                if p.realized_pnl is not None and p.realized_pnl < 0:
                    tier_losses[tier] += 1
                else:
                    # Winner breaks the chain
                    tier_losses[tier] = -999  # Mark as broken

            # Detect current market regime for regime-aware reset
            current_regime = None
            if _REGIME_CHANGE_RESET:
                try:
                    from app.services.ai_scanner import fetch_ohlcv
                    from app.services.market_regime import detect_regime
                    _, ohlcv = await fetch_ohlcv(bot.symbol, bot.timeframe)
                    if ohlcv and len(ohlcv) > 50:
                        ri = detect_regime(bot.symbol, bot.timeframe, ohlcv)
                        current_regime = ri.regime if ri else None
                except Exception as exc:
                    logger.debug(f"[CIRCUIT BREAKER] Regime detection failed for {bot.symbol}: {exc}")

            # Evaluate each tier independently — ONLY block the tier that hit its limit.
            # No cascade to other tiers. Each pair/symbol is independent.
            for tier, count in tier_losses.items():
                if count < 0:
                    continue
                if tier not in allowed_tiers:
                    continue  # Don't evaluate tiers the bot can't trade

                tier_cfg = thresholds.get(tier, _DEFAULT_THRESHOLDS.get(tier, {"consecutive_sl": 3}))
                limit = tier_cfg.get("consecutive_sl", 3)
                current = cb_state.get(tier, {})

                if count >= limit:
                    # Block ONLY this specific tier
                    if not current.get("tripped_at"):
                        now_iso = datetime.now(timezone.utc).isoformat()
                        cb_state[tier] = {
                            "consecutive_sl": count,
                            "tripped_at": now_iso,
                            "limit": limit,
                            "regime_at_block": current_regime,
                        }
                        tripped += 1
                        logger.warning(
                            f"[CIRCUIT BREAKER] {bot.bot_name} ({bot.symbol}) "
                            f"tier {tier} BLOCKED after {count} consecutive SL "
                            f"(limit={limit}, regime={current_regime})"
                        )
                        _queue_notification(
                            bot.bot_name, bot.symbol,
                            f"Tier {tier} BLOQUEADO tras {count} SL consecutivos "
                            f"(límite {limit}, régimen {current_regime})"
                        )
                else:
                    # Under limit — reset if previously tripped
                    if current.get("tripped_at"):
                        cb_state[tier] = {"consecutive_sl": count, "tripped_at": None}
                        reset += 1
                        logger.info(
                            f"[CIRCUIT BREAKER] {bot.bot_name} ({bot.symbol}) "
                            f"tier {tier} reset (count={count} < limit={limit})"
                        )
                        _queue_notification(
                            bot.bot_name, bot.symbol,
                            f"Tier {tier} DESBLOQUEADO — racha {count} < límite {limit}"
                        )

            cfg["circuit_breaker_state"] = cb_state
            bot.ai_signal_config = cfg

        if tripped or reset:
            await db.commit()

    # ── Auto-reactivation: check active bots with tripped tiers ──
    # Design: trigger is per-tier (consecutive SL of same tier), but release is
    # bot-wide to avoid deadlock.  If a tier is blocked but the bot's overall
    # recent performance (last 4h) is healthy, we unblock it so the bot can
    # continue trading.
    reactivated = 0
    active_bots_with_trips = (
        await db.execute(
            select(BotConfig).where(
                BotConfig.ai_signal_mode.is_(True),
                BotConfig.status == "active",
            )
        )
    ).scalars().all()

    MIN_PAUSE_MINUTES = 60
    REACTIVATE_WR_THRESHOLD = 50.0
    REACTIVATE_LOOKBACK_HOURS = 4
    REACTIVATE_MIN_TRADES = 3
    REGIME_RESET_COOLDOWN_MINUTES = 240  # 4h minimum between regime resets
    MAX_CONSECUTIVE_SL_FOR_REGIME_RESET = 2  # Don't regime-reset if ≥2 consecutive SL

    # ── Regime-aware auto-reset: detect regime change for tripped tiers ──
    for bot in active_bots_with_trips:
        cfg = dict(bot.ai_signal_config or {})
        cb_state = cfg.get("circuit_breaker_state", {})
        tripped_tiers = [
            (t, s) for t, s in cb_state.items()
            if isinstance(s, dict) and s.get("tripped_at")
        ]
        if not tripped_tiers:
            continue

        now = datetime.now(timezone.utc)
        tiers_ready = []
        for tier, state in tripped_tiers:
            tripped_at = datetime.fromisoformat(state["tripped_at"])
            minutes_paused = (now - tripped_at).total_seconds() / 60
            if minutes_paused >= MIN_PAUSE_MINUTES:
                tiers_ready.append(tier)
            else:
                logger.debug(
                    f"[CIRCUIT BREAKER] {bot.bot_name} tier {tier} still cooling "
                    f"({minutes_paused:.0f}/{MIN_PAUSE_MINUTES} min)"
                )

        if not tiers_ready:
            continue

        # Detect current regime
        current_regime = None
        try:
            from app.services.ai_scanner import fetch_ohlcv
            from app.services.market_regime import detect_regime
            _, ohlcv = await fetch_ohlcv(bot.symbol, bot.timeframe)
            if ohlcv and len(ohlcv) > 50:
                ri = detect_regime(bot.symbol, bot.timeframe, ohlcv)
                current_regime = ri.regime if ri else None
        except Exception as exc:
            logger.debug(f"[CIRCUIT BREAKER] Regime detection failed for {bot.symbol}: {exc}")

        # 1. Regime-change reset (highest priority) — with safety guards
        regime_reset_tiers = []
        for tier in tiers_ready:
            state = cb_state.get(tier, {})
            blocked_regime = state.get("regime_at_block")
            consecutive_sl = state.get("consecutive_sl", 0)

            # Guard A: Don't regime-reset if too many consecutive SL (execution failing)
            if consecutive_sl >= MAX_CONSECUTIVE_SL_FOR_REGIME_RESET:
                logger.info(
                    f"[CIRCUIT BREAKER] {bot.bot_name} ({bot.symbol}) tier {tier} "
                    f"SKIPPED regime reset — {consecutive_sl} consecutive SL ≥ "
                    f"{MAX_CONSECUTIVE_SL_FOR_REGIME_RESET} (execution edge destroyed, "
                    f"not a regime problem)"
                )
                continue

            # Guard B: Minimum cooldown since last regime reset
            last_regime_reset = state.get("last_regime_reset")
            if last_regime_reset:
                try:
                    last_dt = datetime.fromisoformat(last_regime_reset)
                    minutes_since = (now - last_dt).total_seconds() / 60
                    if minutes_since < REGIME_RESET_COOLDOWN_MINUTES:
                        logger.debug(
                            f"[CIRCUIT BREAKER] {bot.bot_name} tier {tier} regime reset "
                            f"on cooldown ({minutes_since:.0f}/{REGIME_RESET_COOLDOWN_MINUTES} min)"
                        )
                        continue
                except Exception:
                    pass

            if blocked_regime and current_regime and blocked_regime != current_regime:
                cb_state[tier] = {
                    "consecutive_sl": 0,
                    "tripped_at": None,
                    "last_regime_reset": now.isoformat(),
                }
                regime_reset_tiers.append(tier)
                logger.info(
                    f"[CIRCUIT BREAKER] {bot.bot_name} ({bot.symbol}) tier {tier} "
                    f"UNBLOCKED — regime changed from {blocked_regime} to {current_regime}"
                )

        if regime_reset_tiers:
            cfg["circuit_breaker_state"] = cb_state
            bot.ai_signal_config = cfg
            reactivated += len(regime_reset_tiers)
            for tier in regime_reset_tiers:
                _queue_notification(
                    bot.bot_name, bot.symbol,
                    f"Tier {tier} DESBLOQUEADO — régimen cambió de {blocked_regime} a {current_regime}"
                )

        # Remove already-reset tiers from ready list
        tiers_ready = [t for t in tiers_ready if t not in regime_reset_tiers]
        if not tiers_ready:
            continue

        # 2. Bot-wide WR reset (existing logic)
        lookback_since = now - timedelta(hours=REACTIVATE_LOOKBACK_HOURS)
        recent_positions = (
            await db.execute(
                select(Position)
                .where(
                    Position.bot_id == bot.id,
                    Position.status == "closed",
                    Position.source == "ai_bot",
                    Position.closed_at >= lookback_since,
                    Position.realized_pnl.isnot(None),
                )
                .order_by(desc(Position.closed_at))
            )
        ).scalars().all()

        if len(recent_positions) < REACTIVATE_MIN_TRADES:
            logger.info(
                f"[CIRCUIT BREAKER] {bot.bot_name}: not enough recent trades "
                f"({len(recent_positions)}/{REACTIVATE_MIN_TRADES} in last {REACTIVATE_LOOKBACK_HOURS}h) — keeping tiers blocked"
            )
            continue

        wins = sum(1 for p in recent_positions if p.realized_pnl > 0)
        bot_wide_wr = wins / len(recent_positions) * 100

        if bot_wide_wr >= REACTIVATE_WR_THRESHOLD:
            reset_tiers = []
            for tier in tiers_ready:
                cb_state[tier] = {"consecutive_sl": 0, "tripped_at": None}
                reset_tiers.append(tier)
                logger.info(
                    f"[CIRCUIT BREAKER] {bot.bot_name} ({bot.symbol}) tier {tier} "
                    f"UNBLOCKED — bot-wide WR {bot_wide_wr:.0f}% ({wins}/{len(recent_positions)}) "
                    f"last {REACTIVATE_LOOKBACK_HOURS}h ≥ {REACTIVATE_WR_THRESHOLD}%"
                )

            cfg["circuit_breaker_state"] = cb_state
            bot.ai_signal_config = cfg
            reactivated += len(reset_tiers)
            for tier in reset_tiers:
                _queue_notification(
                    bot.bot_name, bot.symbol,
                    f"Tier {tier} DESBLOQUEADO — WR bot {bot_wide_wr:.0f}% "
                    f"({wins}/{len(recent_positions)}) últimas {REACTIVATE_LOOKBACK_HOURS}h"
                )
        else:
            logger.info(
                f"[CIRCUIT BREAKER] {bot.bot_name}: bot-wide WR {bot_wide_wr:.0f}% "
                f"({wins}/{len(recent_positions)}) last {REACTIVATE_LOOKBACK_HOURS}h < {REACTIVATE_WR_THRESHOLD}% — "
                f"tiers remain blocked"
            )

    if tripped or reset or reactivated:
        await db.commit()

    # Send one notification per bot only when a state change actually occurred.
    for bot_name, info in notifications_by_bot.items():
        try:
            notify_circuit_breaker(
                bot_name, info["symbol"],
                "\n".join(info["messages"]),
                title="CIRCUIT BREAKER — CAMBIO DE ESTADO",
            )
        except Exception as notify_exc:
            logger.warning(f"[CIRCUIT BREAKER] Notification failed: {notify_exc}")

    return {"checked": len(bots), "tripped": tripped, "reset": reset, "reactivated": reactivated}
