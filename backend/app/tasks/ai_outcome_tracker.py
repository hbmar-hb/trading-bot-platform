"""
Celery Beat task — auto-labels AI signal outcomes.

Runs every 15 minutes:
1. Load all PENDING ai_signals older than 1 candle period
2. Fetch subsequent candles from Binance (public)
3. Check whether TP1 or SL was hit first (IDEAL mode)
4. Also run REALISTIC simulation using execution analytics
5. Update outcome: SUCCESS | FAILURE_MAX_ADVERSE | FAILURE_BEHAVIORAL | INCONCLUSIVE | EXPIRED | INVALID
   and realistic_outcome / realistic_pnl_pct

Tricotomic labeling:
  SUCCESS: TP1/TP2 reached first
  FAILURE_MAX_ADVERSE: SL reached before any TP
  FAILURE_BEHAVIORAL: TP1 touched first but price reversed to SL later
  EXPIRED: no resolution within N bars → EXCLUDED from training
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta

import ccxt.async_support as ccxt
from celery import shared_task
from loguru import logger
from sqlalchemy import select

from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
from app.services.context_thresholds import update_catr_from_signal

from app.core.constants import TF_SECONDS as _TF_SECONDS

_EXPIRE_BARS = 50  # mark EXPIRED if not resolved within this many bars


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@shared_task(
    name="app.tasks.ai_outcome_tracker.track_outcomes",
    queue="default",
    max_retries=0,
)
def track_outcomes() -> dict:
    try:
        return _run(_track_async())
    except Exception as exc:
        logger.error(f"[AI Tracker] Error: {exc}")
        return {"error": str(exc)}


async def _track_async() -> dict:
    from app.models.ai_signal import AISignal

    now = datetime.now(timezone.utc)
    updated = expired = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AISignal).where(AISignal.outcome == "PENDING")
        )
        pending = result.scalars().all()

    if not pending:
        return {"checked": 0, "updated": 0, "expired": 0}

    exchange = ccxt.binance({"options": {"defaultType": "swap"}})
    try:
        for sig in pending:
            tf_secs = _TF_SECONDS.get(sig.timeframe, 3600)

            # Don't check until at least 1 full candle has closed after signal
            if (now - sig.signal_time).total_seconds() < tf_secs:
                continue

            bars_elapsed = int((now - sig.signal_time).total_seconds() / tf_secs)

            # Download candles for realistic engine even if expired
            try:
                since_ms = int(sig.signal_time.timestamp() * 1000)
                ohlcv = await exchange.fetch_ohlcv(
                    sig.ccxt_symbol, sig.timeframe, since=since_ms, limit=_EXPIRE_BARS
                )
            except Exception as exc:
                logger.warning(f"[AI Tracker] {sig.ticker}/{sig.timeframe} fetch error: {exc}")
                ohlcv = []

            candles_after = []
            if ohlcv:
                candles_after = [c for c in ohlcv if c[0] > int(sig.signal_time.timestamp() * 1000)]

            # Evaluación 1+3: Censored outcomes for signals that never resolve within 72h
            hours_elapsed = (now - sig.created_at).total_seconds() / 3600
            if hours_elapsed > 72:
                try:
                    from ai.services.censored_outcome_tracker import CensoredOutcomeTracker
                    tracker = CensoredOutcomeTracker()
                    censored = tracker.process_single(sig, now)
                    if censored:
                        feat = dict(sig.features or {})
                        feat["censored_weight"] = censored.sample_weight
                        feat["censored_duration_hours"] = censored.duration_hours
                        # Compute near-miss if we have candles
                        near_miss = _compute_near_miss(sig, candles_after) if candles_after else {}
                        await _update_outcome(
                            sig.id,
                            outcome="CENSORED",
                            pnl=None,
                            bars=bars_elapsed,
                            realistic_outcome="CENSORED",
                            realistic_pnl=None,
                            failure_type=None,
                            near_miss=near_miss,
                        )
                        # Update features with censored metadata
                        async with AsyncSessionLocal() as db2:
                            s2 = await db2.get(AISignal, sig.id)
                            if s2:
                                s2.features = feat
                                await db2.commit()
                        expired += 1  # Count as expired for reporting
                        continue
                except Exception as cexc:
                    logger.warning(f"[AI Tracker] Censored processing failed: {cexc}")

            # If truly expired (>50 bars), run realistic engine first before marking EXPIRED
            if bars_elapsed > _EXPIRE_BARS:
                realistic_outcome = None
                realistic_pnl = None
                try:
                    from app.engines.realistic_outcome_engine import simulate_outcome
                    realistic_result = simulate_outcome(sig, candles_after)
                    realistic_outcome = realistic_result.outcome
                    realistic_pnl = realistic_result.pnl_pct
                except Exception as sim_exc:
                    logger.warning(f"[AI Tracker] Realistic simulation failed for expired {sig.ticker}: {sim_exc}")

                # Use INCONCLUSIVE if realistic engine says so, otherwise EXPIRED
                final_outcome = realistic_outcome if realistic_outcome else "EXPIRED"
                final_pnl = realistic_pnl
                if final_outcome == "EXPIRED":
                    final_pnl = None

                near_miss = _compute_near_miss(sig, candles_after) if candles_after else {}
                await _update_outcome(sig.id, final_outcome, final_pnl, bars_elapsed, final_outcome, final_pnl, None, near_miss=near_miss)
                expired += 1
                continue

            try:
                since_ms = int(sig.signal_time.timestamp() * 1000)
                ohlcv = await exchange.fetch_ohlcv(
                    sig.ccxt_symbol, sig.timeframe, since=since_ms, limit=_EXPIRE_BARS
                )
            except Exception as exc:
                logger.warning(f"[AI Tracker] {sig.ticker}/{sig.timeframe} fetch error: {exc}")
                continue

            if not ohlcv:
                continue

            # Skip the signal candle itself (index 0 may overlap)
            candles_after = [c for c in ohlcv if c[0] > int(sig.signal_time.timestamp() * 1000)]

            # ── IDEAL outcome (legacy, now tricotomic) ──
            outcome, pnl, bars, failure_type = _evaluate_outcome(sig, candles_after)

            # ── REALISTIC outcome ──
            realistic_outcome = None
            realistic_pnl = None
            try:
                from app.engines.realistic_outcome_engine import simulate_outcome
                realistic_result = simulate_outcome(sig, candles_after)
                realistic_outcome = realistic_result.outcome
                realistic_pnl = realistic_result.pnl_pct
                logger.debug(
                    f"[AI Tracker] Realistic {sig.ticker}: ideal={outcome} "
                    f"realistic={realistic_outcome}@{realistic_pnl or 0:.2f}%"
                )
            except Exception as sim_exc:
                logger.warning(f"[AI Tracker] Realistic simulation failed for {sig.ticker}: {sim_exc}")
                # Fallback: copy ideal outcome
                realistic_outcome = outcome
                realistic_pnl = pnl

            if outcome:
                near_miss = None
                if outcome in ("FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL"):
                    near_miss = _compute_near_miss(sig, candles_after)
                await _update_outcome(
                    sig.id, outcome, pnl, bars,
                    realistic_outcome, realistic_pnl, failure_type, near_miss=near_miss
                )
                updated += 1
                pnl_str = f"{pnl:.2f}%" if pnl is not None else "N/A"
                real_pnl_str = f"{realistic_pnl:.2f}%" if realistic_pnl is not None else "N/A"
                logger.info(
                    f"[AI Tracker] {sig.ticker}/{sig.timeframe} {sig.direction.upper()} "
                    f"→ ideal={outcome} ({failure_type or 'N/A'}) realistic={realistic_outcome} | "
                    f"pnl={pnl_str} realistic_pnl={real_pnl_str} | bars={bars}"
                )
    finally:
        await exchange.close()

    logger.info(f"[AI Tracker] checked={len(pending)} updated={updated} expired={expired}")
    return {"checked": len(pending), "updated": updated, "expired": expired}


def _has_valid_levels(sig) -> bool:
    """Detecta si TP1 y SL están del lado correcto del entry."""
    if sig.direction == "long":
        return sig.take_profit_1 > sig.entry_price and sig.stop_loss < sig.entry_price
    else:
        return sig.take_profit_1 < sig.entry_price and sig.stop_loss > sig.entry_price


def _evaluate_outcome(sig, candles_after: list) -> tuple[str | None, float | None, int | None, str | None]:
    """
    Walk through candles_after and find which level was hit first: TP1 or SL.
    Now with tricotomic failure detection:
      SUCCESS: TP1 reached first
      FAILURE_MAX_ADVERSE: SL reached first
      FAILURE_BEHAVIORAL: TP1 touched first, but later SL was hit
    Returns (outcome, pnl_pct, bars_to_resolution, failure_type) or (None, None, None, None) if pending.
    """
    if not _has_valid_levels(sig):
        return "INVALID", None, None, None

    is_long = sig.direction == "long"
    entry   = sig.entry_price
    sl      = sig.stop_loss
    tp1     = sig.take_profit_1

    # First pass: find the first resolving candle
    first_resolution_idx = None
    first_outcome = None
    first_ref = None

    for i, c in enumerate(candles_after, start=1):
        if len(c) < 5:
            continue
        _, high, low, close, *_ = c[1], c[2], c[3], c[4]

        if is_long:
            tp_hit = high >= tp1
            sl_hit = low  <= sl
        else:
            tp_hit = low  <= tp1
            sl_hit = high >= sl

        if tp_hit and sl_hit:
            if is_long:
                outcome = "SUCCESS" if close >= entry else "FAILURE_MAX_ADVERSE"
            else:
                outcome = "SUCCESS" if close <= entry else "FAILURE_MAX_ADVERSE"
            ref = tp1 if outcome == "SUCCESS" else sl
            first_resolution_idx = i
            first_outcome = outcome
            first_ref = ref
            break
        elif tp_hit:
            first_resolution_idx = i
            first_outcome = "SUCCESS"
            first_ref = tp1
            break
        elif sl_hit:
            first_resolution_idx = i
            first_outcome = "FAILURE_MAX_ADVERSE"
            first_ref = sl
            break

    if first_resolution_idx is None:
        return None, None, None, None

    # If first resolution was SUCCESS (TP1 hit), check for behavioral failure:
    # Did SL get hit in a subsequent candle?
    if first_outcome == "SUCCESS":
        for j in range(first_resolution_idx, len(candles_after)):
            c = candles_after[j]
            if len(c) < 5:
                continue
            _, high, low, close, *_ = c[1], c[2], c[3], c[4]

            if is_long:
                sl_hit = low <= sl
            else:
                sl_hit = high >= sl

            if sl_hit:
                # TP1 hit first, then SL hit later → BEHAVIORAL failure
                pnl = (entry - sl) / entry * 100
                if not is_long:
                    pnl = (sl - entry) / entry * 100
                return "FAILURE_BEHAVIORAL", round(-abs(pnl), 3), first_resolution_idx, "BEHAVIORAL"

    # Normal resolution
    pnl = (first_ref - entry) / entry * 100
    if not is_long:
        pnl = (entry - first_ref) / entry * 100

    failure_type = None
    if first_outcome == "FAILURE_MAX_ADVERSE":
        failure_type = "MAX_ADVERSE"

    return first_outcome, round(pnl, 3), first_resolution_idx, failure_type


def _compute_near_miss(sig, candles_after: list) -> dict:
    """
    Calculate how close price came to TP1 before reversing / expiring.
    Returns dict with near-miss metrics for censored / failed signals.
    """
    if not candles_after or not _has_valid_levels(sig):
        return {}

    is_long = sig.direction == "long"
    entry = sig.entry_price
    sl = sig.stop_loss
    tp1 = sig.take_profit_1

    # Distance from entry to TP1 (always positive)
    tp_distance = abs(tp1 - entry)
    if tp_distance <= 0:
        return {}

    # Track max favorable excursion (MFE) — best price in favorable direction
    max_favorable = entry
    max_favorable_idx = 0
    forward_levels_touched = 0
    best_unfilled_level = None
    best_unfilled_price = None

    # Get forward levels from features if available
    forward_levels = (sig.features or {}).get("forward_levels", [])
    forward_prices = sorted([float(l["price"]) for l in forward_levels], reverse=is_long)

    for i, c in enumerate(candles_after, start=1):
        if len(c) < 5:
            continue
        _, high, low, close, *_ = c[1], c[2], c[3], c[4]

        if is_long:
            best_in_candle = high
            # Check forward levels touched
            for fp in forward_prices:
                if high >= fp:
                    forward_levels_touched += 1
                    if best_unfilled_level is None and fp < tp1:
                        best_unfilled_level = fp
                    break
        else:
            best_in_candle = low
            for fp in forward_prices:
                if low <= fp:
                    forward_levels_touched += 1
                    if best_unfilled_level is None and fp > tp1:
                        best_unfilled_level = fp
                    break

        # Track best favorable price
        if is_long:
            if best_in_candle > max_favorable:
                max_favorable = best_in_candle
                max_favorable_idx = i
        else:
            if best_in_candle < max_favorable:
                max_favorable = best_in_candle
                max_favorable_idx = i

    # Compute near-miss %: how much of the TP distance was covered
    favorable_move = abs(max_favorable - entry)
    near_miss_pct = favorable_move / tp_distance if tp_distance > 0 else 0.0

    # Check if any forward level was the best achieved (but TP not reached)
    if best_unfilled_level is not None:
        best_unfilled_price = best_unfilled_level

    result = {
        "near_miss_tp1_pct": round(min(near_miss_pct, 2.0), 4),
        "max_favorable_distance": round(favorable_move, 4),
        "max_favorable_idx": max_favorable_idx,
        "forward_levels_touched": forward_levels_touched,
    }
    if best_unfilled_price is not None:
        result["best_unfilled_level"] = round(best_unfilled_price, 4)

    return result


async def _update_outcome(
    signal_id,
    outcome: str,
    pnl: float | None,
    bars: int | None,
    realistic_outcome: str | None,
    realistic_pnl: float | None,
    failure_type: str | None,
    near_miss: dict | None = None,
):
    from app.models.ai_signal import AISignal
    from app.models.llm_signal_diagnosis import LLMSignalDiagnosis

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        sig = await db.get(AISignal, signal_id)
        if sig:
            sig.outcome      = outcome
            sig.pnl_pct      = pnl
            sig.outcome_bars = bars
            sig.resolved_at  = now
            # Realistic outcome
            if realistic_outcome is not None:
                sig.realistic_outcome = realistic_outcome
            if realistic_pnl is not None:
                sig.realistic_pnl_pct = realistic_pnl
            # Failure type for attribution
            if failure_type:
                feat = dict(sig.features or {})
                feat["failure_type"] = failure_type
                sig.features = feat
            # Near-miss metrics for censored / expired / max-adverse signals
            if near_miss:
                feat = dict(sig.features or {})
                feat.update(near_miss)
                sig.features = feat
            await db.commit()

            # CATR: actualizar thresholds contextuales con resultado real
            try:
                catr_pnl = realistic_pnl if realistic_pnl is not None else pnl
                if catr_pnl is not None:
                    update_catr_from_signal(sig, outcome, catr_pnl)
            except Exception:
                pass  # Never fail because of CATR

            # Circuit breaker: record confident failures
            try:
                from risk.circuit_breaker import CircuitBreaker
                cb = CircuitBreaker()
                success_prob = sig.success_probability
                if success_prob is not None:
                    cb.record(predicted_prob=success_prob, actual_outcome=outcome)
            except Exception:
                pass  # Never fail because of circuit breaker

            # Shadow mode: resolve prediction with actual outcome
            try:
                from ai.services.shadow_mode import ShadowDeployer
                sd = ShadowDeployer()
                sd.resolve(str(sig.id), outcome, pnl)
            except Exception:
                pass  # Never fail because of shadow mode

        # Enrich associated LLM diagnoses with final outcome
        try:
            from sqlalchemy import update
            await db.execute(
                update(LLMSignalDiagnosis)
                .where(LLMSignalDiagnosis.ai_signal_id == signal_id)
                .values(outcome=outcome, pnl_pct=pnl, resolved_at=now)
            )
            await db.commit()
        except Exception:
            pass

        # Resolve shadow evaluations for this signal
        try:
            from sqlalchemy import update
            from app.models.ai_signal_shadow_evaluation import AISignalShadowEvaluation
            await db.execute(
                update(AISignalShadowEvaluation)
                .where(AISignalShadowEvaluation.ai_signal_id == signal_id)
                .values(outcome=outcome, pnl_pct=pnl, resolved_at=now)
            )
            await db.commit()
        except Exception:
            pass
