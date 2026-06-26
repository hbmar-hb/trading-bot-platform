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
import json
from datetime import datetime, timezone

import ccxt.async_support as ccxt
from celery import shared_task
from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.services.database import SessionLocal
from app.services.cache import sync_redis
from app.models.ai_scan import AIWatchlistItem, AILatestScan
from app.services.ai_scanner import (
    build_signal, fetch_ohlcv, htf_for, signal_to_dict, to_ccxt,
)
from app.services.scan_event_publisher import (
    publish_scan_event_sync, new_scan_id,
)
from app.core.constants import TF_FALLBACK_CHAIN, cdc_for

# Timeframes to scan for every symbol in the AI watchlist.
# The IA will later choose the best timeframe via the signal score.
DEFAULT_SCAN_TIMEFRAMES = ["15m", "30m", "1h", "2h", "4h"]

_SCAN_LOCK_KEY = "lock:ai_scan_watchlists"
# The lock must outlive the longest expected scan, but it should not block
# the next 15-minute beat forever if a worker dies without releasing it.
_SCAN_LOCK_TTL_SECONDS = 1200  # 20 min — scans should finish well under this

# Fetch concurrency: Binance swap IP limits are generous; 10 parallel requests
# with rate-limiting keeps a 16-symbol × 5-timeframe scan under ~60s.
_FETCH_CONCURRENCY = 10

# Short-term OHLCV cache so repeated scans / fallback / CDC fetches reuse data
# and do not hammer the exchange with identical requests.
_OHLCV_CACHE_TTL_SECONDS = 300  # 5 min
_OHLCV_CACHE_PREFIX = "ai_scan:ohlcv"


def _ohlcv_cache_key(symbol: str, timeframe: str) -> str:
    return f"{_OHLCV_CACHE_PREFIX}:{symbol.upper()}:{timeframe}"


def _get_cached_ohlcv(symbol: str, timeframe: str) -> list | None:
    try:
        raw = sync_redis.get(_ohlcv_cache_key(symbol, timeframe))
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _set_cached_ohlcv(symbol: str, timeframe: str, ohlcv: list) -> None:
    try:
        sync_redis.setex(
            _ohlcv_cache_key(symbol, timeframe),
            _OHLCV_CACHE_TTL_SECONDS,
            json.dumps(ohlcv),
        )
    except Exception:
        pass


async def _fetch_cached(
    exchange: ccxt.binance,
    sem: asyncio.Semaphore,
    symbol: str,
    timeframe: str,
) -> tuple[str, list | None]:
    """Fetch OHLCV, using a short-lived Redis cache to avoid redundant calls."""
    cached = _get_cached_ohlcv(symbol, timeframe)
    if cached is not None:
        return symbol, cached

    async with sem:
        try:
            ohlcv = await exchange.fetch_ohlcv(
                to_ccxt(symbol), timeframe, limit=200
            )
        except Exception as exc:
            logger.debug(
                f"[AI SCAN] fetch failed {symbol}/{timeframe}: {exc}"
            )
            ohlcv = None

    if ohlcv:
        _set_cached_ohlcv(symbol, timeframe, ohlcv)
    return symbol, ohlcv


async def _fetch_all(
    exchange: ccxt.binance,
    sem: asyncio.Semaphore,
    pairs: list[tuple[str, str]],
    htf_pairs: list[tuple[str, str]],
    unique_symbols: list[str],
) -> list[tuple[str, list | None]]:
    return await asyncio.gather(
        *(_fetch_cached(exchange, sem, sym, tf) for sym, tf in pairs),
        *(_fetch_cached(exchange, sem, sym, htf) for sym, htf in htf_pairs),
        *(_fetch_cached(exchange, sem, sym, "1d") for sym in unique_symbols),
    )


async def _close_exchange(exchange: ccxt.binance) -> None:
    try:
        await exchange.close()
    except Exception:
        pass


async def _ltf_cdc_confirmed(
    exchange: ccxt.binance,
    sem: asyncio.Semaphore,
    symbol: str,
    primary_tf: str,
    direction: str,
) -> bool:
    """Check LTF CDC confirmation, reusing cached OHLCV when available."""
    ltf = cdc_for(primary_tf)
    if not ltf or not direction:
        return False

    cached = _get_cached_ohlcv(symbol, ltf)
    ohlcv = cached
    if ohlcv is None:
        _, ohlcv = await _fetch_cached(exchange, sem, symbol, ltf)

    if not ohlcv or len(ohlcv) < 30:
        return False

    try:
        from app.services.confirmation_scanner import check_ltf_cdc
        return check_ltf_cdc(ohlcv, direction)
    except Exception as exc:
        logger.warning(f"[AI SCAN] {symbol}/{primary_tf}: LTF CDC check failed: {exc}")
        return False


def _acquire_scan_lock() -> bool:
    """Try to acquire a Redis lock so only one scan runs at a time."""
    acquired = sync_redis.set(
        _SCAN_LOCK_KEY,
        datetime.now(timezone.utc).isoformat(),
        nx=True,
        ex=_SCAN_LOCK_TTL_SECONDS,
    )
    return bool(acquired)


def _release_scan_lock() -> None:
    sync_redis.delete(_SCAN_LOCK_KEY)


@shared_task(
    bind=True,
    max_retries=1,
    name="app.tasks.ai_scan_task.scan_all_watchlists",
    queue="default",
    soft_time_limit=600,  # 10 min — start warning
    time_limit=900,       # 15 min — hard kill (must fit inside the 15m beat)
)
def scan_all_watchlists(self):
    """Scan every (symbol, timeframe) pair from user watchlists."""
    if not _acquire_scan_lock():
        logger.info("[AI SCAN] Another scan is already running; skipping this beat.")
        return {"status": "skipped", "reason": "another_scan_running"}

    start = datetime.now(timezone.utc)
    scan_id = new_scan_id()
    publish_scan_event_sync(
        source="celery",
        scan_id=scan_id,
        symbol="_ALL_",
        timeframe="_ALL_",
        status="SCAN_START",
        message=f"Scan started at {start.isoformat()}",
    )
    try:
        result = _run_scan(scan_id)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(f"[AI SCAN] Completed in {elapsed:.1f}s")
        publish_scan_event_sync(
            source="celery",
            scan_id=scan_id,
            symbol="_ALL_",
            timeframe="_ALL_",
            status="SCAN_END",
            message=f"Scan completed: {result.get('scanned', 0)} pairs, {result.get('signals', 0)} signals",
        )
        return result
    except Exception as exc:
        logger.error(f"[AI SCAN] Fatal error: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60)
    finally:
        _release_scan_lock()


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


def _run_scan(scan_id: str) -> dict:
    # ── 1. Read watchlist (sync DB) ───────────────────────────
    with SessionLocal() as db:
        symbols = [r[0] for r in db.execute(
            select(AIWatchlistItem.symbol).distinct()
        ).all()]

    if not symbols:
        return {"status": "no_watchlist_items"}

    # Scan every configured timeframe for each watched symbol.
    # The IA chooses the optimal timeframe via the per-signal confluence score.
    pairs: list[tuple[str, str]] = [
        (sym, tf) for sym in symbols for tf in DEFAULT_SCAN_TIMEFRAMES
    ]
    htf_pairs = list({(sym, htf_for(tf)) for sym, tf in pairs if htf_for(tf)})

    # Fase A: fetch daily candles once per symbol for SMC macro context
    unique_symbols = list({sym for sym, _ in pairs})

    # ── 2. Fetch OHLCV concurrently (pure async, no DB) ───────
    exchange = ccxt.binance({
        "options": {"defaultType": "swap"},
        "enableRateLimit": True,
        "timeout": 20000,
    })
    sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

    def _emit(status, symbol, timeframe, **kwargs):
        """Publish a lightweight scan event to the live stream."""
        try:
            publish_scan_event_sync(
                source="celery",
                scan_id=scan_id,
                symbol=symbol,
                timeframe=timeframe,
                status=status,
                **kwargs,
            )
        except Exception:
            pass

    try:
        all_fetches = _run_async(_fetch_all(exchange, sem, pairs, htf_pairs, unique_symbols))

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
        # Collect signal activations and emit them ordered by score per symbol so
        # the highest-scoring timeframe is evaluated first by the bot activator.
        pending_activations: list[tuple[str, float, str]] = []

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
                    cdc_confirmed = _run_async(
                        _ltf_cdc_confirmed(exchange, sem, sym, tf, sig.direction)
                    )

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

                    _emit(
                        "SIGNAL",
                        sym,
                        tf,
                        direction=sig.direction,
                        score=sig.score,
                        confidence=sig.confidence,
                        quality_tier=sig.quality_tier,
                        anti_fake_status=sig.anti_fake_status,
                        success_probability=sig.success_probability,
                        regime=sig.features.get("market_regime"),
                        regime_confidence=sig.features.get("regime_confidence"),
                        features_preview={
                            "entry_type": sig.features.get("entry_type"),
                            "ltf_cdc_confirmed": sig.features.get("ltf_cdc_confirmed"),
                            "htf_bias": sig.features.get("htf_bias"),
                            "macro_caution": sig.features.get("macro_caution"),
                            "market_quality": sig.features.get("market_quality"),
                        },
                    )

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
                            logger.debug(f"[AI SCAN] {sym}/{tf}: shadow predictions recorded for {sig.id}")
                        except Exception as exc:
                            logger.warning(f"[AI SCAN] {sym}/{tf}: failed to record shadow predictions: {exc}")
                        signals += 1
                        pending_activations.append((sym, float(sig.score), str(sig.id)))
                    except IntegrityError:
                        db.rollback()
                        logger.info(f"[AI SCAN] {sym}/{tf}: dedup — signal already exists (race guard)")
                        _upsert_latest_scan_sync(db, sym, tf, result_dict, sig)
                        continue
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
                    _emit(
                        "NO_SIGNAL",
                        sym,
                        tf,
                        rejection_reason=reason,
                        rejection_context=ctx,
                        features_preview={
                            "htf_conflict": ctx.get("htf_conflict"),
                            "regime_reason": ctx.get("regime_reason"),
                            "market_quality": ctx.get("market_quality"),
                            "macro_caution": ctx.get("macro_caution"),
                            "macro_reason": ctx.get("macro_reason"),
                        },
                    )
                    _upsert_latest_scan_sync(db, sym, tf, result_dict)
                    no_signal_pairs.append((sym, tf))

            db.commit()

            # ── 4. Timeframe fallback: scan higher TFs for pairs with NO_SIGNAL ──
            if no_signal_pairs:
                extra_signals = _run_fallback_scans(
                    db, no_signal_pairs, pairs_scanned, htf_cache, daily_cache,
                    pending_activations, exchange, sem,
                )
                signals += extra_signals
                db.commit()

            # Emit activations ordered by score per symbol so the highest-scoring
            # timeframe reaches the bot activator first. Cooldown/max_concurrent will
            # naturally drop lower-scoring timeframes of the same symbol.
            if pending_activations:
                from itertools import groupby
                pending_activations.sort(key=lambda x: (x[0], -x[1]))
                for sym, group in groupby(pending_activations, key=lambda x: x[0]):
                    for _, _, sig_id in group:
                        try:
                            from app.tasks.bot_activator_task import activate_signal
                            activate_signal.delay(sig_id)
                        except Exception as exc:
                            logger.warning(f"[AI SCAN] failed to queue activation for {sig_id}: {exc}")
                        try:
                            from app.tasks.llm_tasks import generate_signal_diagnosis
                            generate_signal_diagnosis.delay(sig_id, "anti_fake")
                        except Exception:
                            pass

    finally:
        _run_async(_close_exchange(exchange))

    scanned_count = len(pairs)
    logger.info(f"[AI SCAN] scanned={scanned_count} signals={signals}")

    # Liberar referencias grandes
    try:
        del ltf_fetches, htf_cache, daily_cache, pairs, htf_pairs, unique_symbols
    except NameError:
        pass
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


def _run_fallback_scans(
    db,
    no_signal_pairs,
    pairs_scanned,
    htf_cache,
    daily_cache,
    pending_activations: list,
    exchange: ccxt.binance,
    sem: asyncio.Semaphore,
) -> int:
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
                _, ohlcv_fb = _run_async(
                    _fetch_cached(exchange, sem, sym, fallback_tf)
                )
                if not ohlcv_fb or len(ohlcv_fb) < 50:
                    continue
                htf_fb = htf_for(fallback_tf)
                htf_ohlcv_fb = htf_cache.get((sym, htf_fb)) if htf_fb else None
                if htf_fb and htf_ohlcv_fb is None:
                    _, htf_ohlcv_fb = _run_async(
                        _fetch_cached(exchange, sem, sym, htf_fb)
                    )
                daily_ohlcv_fb = daily_cache.get((sym, "1d")) if fallback_tf != "1d" else ohlcv_fb
                if daily_ohlcv_fb is None and fallback_tf != "1d":
                    _, daily_ohlcv_fb = _run_async(
                        _fetch_cached(exchange, sem, sym, "1d")
                    )
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
                    pending_activations.append((sym, float(sig_fb.score), str(sig_fb.id)))
                    break
                else:
                    _upsert_latest_scan_sync(db, sym, fallback_tf, result_dict_fb)
            except Exception as exc:
                logger.warning(f"[AI SCAN FALLBACK] {sym}/{fallback_tf} error: {exc}")

    return extra_signals
