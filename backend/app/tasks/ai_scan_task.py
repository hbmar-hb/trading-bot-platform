"""Background AI scanner — runs every 5 minutes via Celery Beat.

Scans all unique (symbol, timeframe) pairs from user watchlists
and persists results to ai_latest_scans so the frontend always
shows the latest state even when users are not on the page.

DB operations use the SYNC SessionLocal to avoid asyncpg pool/event-loop
conflicts that happen when asyncio.run() is called repeatedly in the same
Celery forked worker process.  Only the HTTP OHLCV fetches need asyncio.
"""
from __future__ import annotations

import asyncio
import gc
from datetime import datetime, timezone

from celery import shared_task
from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.services.database import SessionLocal
from app.models.ai_scan import AIWatchlistItem, AILatestScan
from app.services.ai_scanner import (
    build_signal, fetch_ohlcv, htf_for, signal_to_dict,
)
from app.core.constants import TF_FALLBACK_CHAIN


@shared_task(
    bind=True,
    max_retries=1,
    name="app.tasks.ai_scan_task.scan_all_watchlists",
    queue="default",
)
def scan_all_watchlists(self):
    """Scan every (symbol, timeframe) pair from user watchlists."""
    try:
        return _run_scan()
    except Exception as exc:
        logger.error(f"[AI SCAN] Fatal error: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60)


def _run_async(coro):
    """Run async coroutine reusing the thread-local loop if available."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _run_scan() -> dict:
    # ── 1. Read watchlist (sync DB) ───────────────────────────
    from app.services.auto_timeframe import resolve_best_timeframe_sync

    with SessionLocal() as db:
        rows = db.execute(
            select(AIWatchlistItem.symbol, AIWatchlistItem.timeframe).distinct()
        ).all()

    if not rows:
        return {"status": "no_watchlist_items"}

    # Resolve "auto" timeframes to the best historical TF per ticker
    resolved_pairs: list[tuple[str, str]] = []
    with SessionLocal() as db:
        for row in rows:
            sym = row.symbol
            tf = row.timeframe
            if tf == "auto":
                resolved_tf = resolve_best_timeframe_sync(sym, db)
                row.resolved_timeframe = resolved_tf
                resolved_pairs.append((sym, resolved_tf))
                logger.info(f"[AI SCAN] Resolved auto timeframe: {sym} → {resolved_tf} (user={row.user_id})")
            else:
                resolved_pairs.append((sym, tf))
        db.commit()

    pairs     = list({(sym, tf) for sym, tf in resolved_pairs})
    htf_pairs = list({(sym, htf_for(tf)) for sym, tf in pairs if htf_for(tf)})

    # Fase A: fetch daily candles once per symbol for SMC macro context
    unique_symbols = list({sym for sym, _ in pairs})

    # ── 2. Fetch OHLCV concurrently (pure async, no DB) ───────
    async def _fetch_all():
        sem = asyncio.Semaphore(3)  # reducido para limitar memoria simultánea
        return await asyncio.gather(
            *[fetch_ohlcv(sym, tf,  sem) for sym, tf  in pairs],
            *[fetch_ohlcv(sym, htf, sem) for sym, htf in htf_pairs],
            *[fetch_ohlcv(sym, "1d", sem) for sym in unique_symbols],
        )

    all_fetches = _run_async(_fetch_all())

    ltf_fetches = all_fetches[:len(pairs)]
    htf_cache: dict[tuple[str, str], list | None] = {
        (sym, htf): ohlcv
        for (sym, htf), (_, ohlcv) in zip(htf_pairs, all_fetches[len(pairs):len(pairs)+len(htf_pairs)])
    }
    daily_cache: dict[tuple[str, str], list | None] = {
        (sym, "1d"): ohlcv
        for sym, (_, ohlcv) in zip(unique_symbols, all_fetches[len(pairs)+len(htf_pairs):])
    }

    # Liberar lista bruta grande apenas ya no se necesita
    del all_fetches

    # ── 3. Analyse + write results (sync DB) ──────────────────
    signals = 0
    no_signal_pairs: list[tuple[str, str]] = []
    pairs_scanned: set[tuple[str, str]] = set()

    with SessionLocal() as db:
        for (sym, tf), (_, ohlcv) in zip(pairs, ltf_fetches):
            pairs_scanned.add((sym, tf))
            if not ohlcv or len(ohlcv) < 50:
                logger.info(f"[AI SCAN] {sym}/{tf}: skipped — insufficient OHLCV ({len(ohlcv) if ohlcv else 0} candles)")
                continue

            htf      = htf_for(tf)
            htf_ohlcv = htf_cache.get((sym, htf)) if htf else None
            daily_ohlcv = daily_cache.get((sym, "1d")) if tf != "1d" else ohlcv
            weekly_ohlcv = htf_cache.get((sym, "1w")) if htf == "1w" else None
            result_dict, sig = build_signal(
                sym, tf, ohlcv,
                htf_ohlcv=htf_ohlcv,
                candles_1d=daily_ohlcv,
                candles_1w=weekly_ohlcv,
            )

            # Liberar referencias por par inmediatamente
            del ohlcv, htf_ohlcv, daily_ohlcv, weekly_ohlcv

            if sig:
                logger.info(
                    f"[AI SCAN] {sym}/{tf}: SIGNAL {sig.direction} "
                    f"score={sig.score:.1f} conf={sig.confidence} "
                    f"prob={sig.success_probability} tier={sig.quality_tier}"
                )

                # ── SMC Confirmation Entry: hybrid soft feature ──────────────────
                # Instead of hard-gating on CDC, we create the signal immediately
                # and let the ML model learn CE vs RE performance differential.
                def _ltf_for_timeframe(timeframe: str) -> str:
                    """Return appropriate lower timeframe for CDC confirmation."""
                    mapping = {
                        "1m": "1m", "3m": "1m", "5m": "1m",
                        "15m": "5m", "30m": "5m",
                        "1h": "15m", "2h": "15m",
                        "4h": "1h", "6h": "1h", "8h": "1h", "12h": "1h",
                        "1d": "4h", "3d": "4h", "1w": "4h",
                    }
                    return mapping.get(timeframe, "5m")

                cdc_confirmed = False
                try:
                    from app.services.confirmation_scanner import check_ltf_cdc
                    ltf = _ltf_for_timeframe(tf)
                    _, ltf_ohlcv = _run_async(fetch_ohlcv(sym, ltf))
                    if ltf_ohlcv and len(ltf_ohlcv) >= 30:
                        cdc_confirmed = check_ltf_cdc(ltf_ohlcv, sig.direction)
                except Exception as exc:
                    logger.warning(f"[AI SCAN] {sym}/{tf}: LTF CDC check failed: {exc}")

                feat = dict(sig.features or {})
                feat["ltf_cdc_confirmed"] = cdc_confirmed
                if cdc_confirmed:
                    feat["entry_type"] = "CE"
                    feat["entry_confidence"] = 0.9
                else:
                    feat["entry_type"] = "RE"
                    feat["entry_confidence"] = 0.6
                    # Still add to watchlist for tracking / potential CE upgrade
                    try:
                        from app.services.confirmation_scanner import add_to_watchlist
                        from app.services.cache import sync_redis
                        add_to_watchlist(
                            sync_redis,
                            symbol=sym,
                            direction=sig.direction,
                            timeframe=tf,
                            poi_price=sig.entry_price,
                            score=sig.score,
                            quality_tier=sig.quality_tier,
                        )
                    except Exception as exc:
                        logger.warning(f"[AI SCAN] {sym}/{tf}: failed to add to watchlist: {exc}")
                    logger.info(
                        f"[AI SCAN] {sym}/{tf}: Risk Entry (RE) — no CDC yet, "
                        f"signal created with reduced confidence"
                    )
                sig.features = feat

                # Connect backtest engine to training: inject rolling historical metrics
                try:
                    from app.services.backtest_metrics_service import get_backtest_metrics_sync
                    bt_metrics = get_backtest_metrics_sync(db, sig.ticker, sig.timeframe, lookback_days=30)
                    feat = dict(sig.features or {})
                    feat.update(bt_metrics)
                    sig.features = feat
                except Exception:
                    pass
                # Dedup: skip if a signal with identical candle already exists
                from app.models.ai_signal import AISignal
                existing = db.execute(
                    select(AISignal.id).where(
                        AISignal.ticker == sig.ticker,
                        AISignal.timeframe == sig.timeframe,
                        AISignal.direction == sig.direction,
                        AISignal.signal_time == sig.signal_time,
                    ).limit(1)
                ).first()
                if existing:
                    logger.info(f"[AI SCAN] {sym}/{tf}: dedup — signal already exists")
                    _upsert_latest_scan_sync(db, sym, tf, result_dict, sig)
                    continue

                try:
                    db.add(sig)
                    db.commit()
                    db.refresh(sig)
                    _upsert_latest_scan_sync(db, sym, tf, result_dict, sig)
                    # Record shadow predictions only after the signal has a real id
                    try:
                        from app.services.ai_scanner import record_shadow_for_signal
                        record_shadow_for_signal(str(sig.id), result_dict)
                    except Exception:
                        pass
                    signals += 1
                    from app.tasks.bot_activator_task import activate_signal
                    activate_signal.delay(str(sig.id))
                except IntegrityError:
                    db.rollback()
                    logger.info(f"[AI SCAN] {sym}/{tf}: dedup — signal already exists (race guard)")
                    _upsert_latest_scan_sync(db, sym, tf, result_dict, sig)
                    continue
                # Trigger LLM diagnosis for ALL signals so bot activator can read it in real-time
                try:
                    from app.tasks.llm_tasks import generate_signal_diagnosis
                    generate_signal_diagnosis.delay(str(sig.id), "anti_fake")
                except Exception:
                    pass
            else:
                ctx = result_dict.get("context", {})
                reason = "no_setup"
                if "htf_conflict" in ctx:
                    reason = f"htf_conflict={ctx['htf_conflict']}"
                elif "regime_blocked" in ctx:
                    reason = f"regime_blocked ({ctx.get('regime_reason', '')})"
                elif "macro_blocked" in ctx:
                    reason = "macro_blocked"
                elif "market_quality" in ctx:
                    reason = f"market_quality={ctx.get('market_quality')}"
                elif "circuit_breaker" in ctx:
                    reason = "circuit_breaker"
                logger.info(f"[AI SCAN] {sym}/{tf}: NO_SIGNAL — {reason}")
                _upsert_latest_scan_sync(db, sym, tf, result_dict)
                no_signal_pairs.append((sym, tf))

        db.commit()

        # ── 4. Timeframe fallback: scan higher TFs for pairs with NO_SIGNAL ──
        if no_signal_pairs:
            extra_signals = _run_fallback_scans(db, no_signal_pairs, pairs_scanned, htf_cache, daily_cache)
            signals += extra_signals
            db.commit()

    scanned_count = len(pairs)
    logger.info(f"[AI SCAN] scanned={scanned_count} signals={signals}")

    # Liberar caches explícitamente
    del ltf_fetches, htf_cache, daily_cache, pairs, htf_pairs, unique_symbols
    gc.collect()

    return {"status": "ok", "scanned": scanned_count, "signals": signals}


def _upsert_latest_scan_sync(db, symbol, timeframe, result_dict, sig=None):
    signal_data = signal_to_dict(sig) if sig else None
    values = {
        "symbol":      symbol,
        "timeframe":   timeframe,
        "status":      result_dict.get("status", "NO_SIGNAL"),
        "context":     result_dict.get("context"),
        "signal_data": signal_data,
        "signal_id":   sig.id if sig else None,
        "scanned_at":  datetime.now(timezone.utc),
    }
    stmt = (
        pg_insert(AILatestScan)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["symbol", "timeframe"],
            set_={k: values[k] for k in ("status", "context", "signal_data", "signal_id", "scanned_at")},
        )
    )
    db.execute(stmt)


def _upsert_fallback_scan_sync(db, symbol, primary_tf, fallback_tf, sig):
    """Mark primary TF scan as having a fallback signal from a higher TF."""
    signal_data = signal_to_dict(sig) if sig else None
    values = {
        "symbol": symbol,
        "timeframe": primary_tf,
        "status": "FALLBACK",
        "context": {
            "fallback_from": fallback_tf,
            "fallback_signal_id": str(sig.id) if sig else None,
        },
        "signal_data": signal_data,
        "signal_id": sig.id if sig else None,
        "scanned_at": datetime.now(timezone.utc),
    }
    stmt = (
        pg_insert(AILatestScan)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["symbol", "timeframe"],
            set_={k: values[k] for k in ("status", "context", "signal_data", "signal_id", "scanned_at")},
        )
    )
    db.execute(stmt)


def _run_fallback_scans(db, no_signal_pairs, pairs_scanned, htf_cache, daily_cache) -> int:
    """For each (symbol, tf) that had NO_SIGNAL, try higher TFs in cascade.

    Returns number of new signals generated from fallback TFs.
    """
    from app.models.ai_signal import AISignal

    extra_signals = 0

    for sym, tf in no_signal_pairs:
        fallback_tfs = TF_FALLBACK_CHAIN.get(tf, [])
        if not fallback_tfs:
            continue

        for fallback_tf in fallback_tfs:
            # Case A: fallback TF was already scanned in main loop — reuse if SIGNAL
            if (sym, fallback_tf) in pairs_scanned:
                existing = db.execute(
                    select(AILatestScan)
                    .where(
                        AILatestScan.symbol == sym,
                        AILatestScan.timeframe == fallback_tf,
                    )
                ).scalar_one_or_none()
                if existing and existing.status == "SIGNAL" and existing.signal_id:
                    logger.info(
                        f"[AI SCAN FALLBACK] {sym}/{tf} → reusing {fallback_tf} signal"
                    )
                    _upsert_fallback_scan_sync(db, sym, tf, fallback_tf, None)
                    break
                continue

            # Case B: fetch OHLCV and build signal for fallback TF
            try:
                _, ohlcv_fb = _run_async(fetch_ohlcv(sym, fallback_tf))
                if not ohlcv_fb or len(ohlcv_fb) < 50:
                    continue
                htf_fb = htf_for(fallback_tf)
                htf_ohlcv_fb = htf_cache.get((sym, htf_fb)) if htf_fb else None
                daily_ohlcv_fb = daily_cache.get((sym, "1d")) if fallback_tf != "1d" else ohlcv_fb
                weekly_ohlcv_fb = htf_cache.get((sym, "1w")) if htf_fb == "1w" else None
                result_dict_fb, sig_fb = build_signal(
                    sym, fallback_tf, ohlcv_fb,
                    htf_ohlcv=htf_ohlcv_fb,
                    candles_1d=daily_ohlcv_fb,
                    candles_1w=weekly_ohlcv_fb,
                )
                if sig_fb:
                    if sig_fb.score < 55:
                        logger.info(
                            f"[AI SCAN FALLBACK] {sym}/{fallback_tf}: score={sig_fb.score:.1f} < 55 — no opera"
                        )
                        _upsert_latest_scan_sync(db, sym, fallback_tf, result_dict_fb)
                        continue
                    logger.info(
                        f"[AI SCAN FALLBACK] {sym}/{tf} → found signal in {fallback_tf} "
                        f"{sig_fb.direction} score={sig_fb.score:.1f}"
                    )
                    # Dedup
                    dup = db.execute(
                        select(AISignal.id).where(
                            AISignal.ticker == sig_fb.ticker,
                            AISignal.timeframe == sig_fb.timeframe,
                            AISignal.direction == sig_fb.direction,
                            AISignal.signal_time == sig_fb.signal_time,
                        ).limit(1)
                    ).scalar_one_or_none()
                    if dup:
                        _upsert_latest_scan_sync(db, sym, fallback_tf, result_dict_fb, sig_fb)
                        _upsert_fallback_scan_sync(db, sym, tf, fallback_tf, sig_fb)
                        break

                    db.add(sig_fb)
                    db.commit()
                    db.refresh(sig_fb)
                    _upsert_latest_scan_sync(db, sym, fallback_tf, result_dict_fb, sig_fb)
                    _upsert_fallback_scan_sync(db, sym, tf, fallback_tf, sig_fb)
                    extra_signals += 1
                    from app.tasks.bot_activator_task import activate_signal
                    activate_signal.delay(str(sig_fb.id))
                    break
                else:
                    _upsert_latest_scan_sync(db, sym, fallback_tf, result_dict_fb)
            except Exception as exc:
                logger.warning(f"[AI SCAN FALLBACK] {sym}/{fallback_tf} error: {exc}")

    return extra_signals
