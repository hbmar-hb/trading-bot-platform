"""SMC Confirmation Entry scanner — runs every 5 minutes via Celery Beat.

Reads the Redis watchlist of setups that passed the main scanner (15m/1h)
but lacked CDC confirmation in the LTF (5m). Fetches fresh 5m data and,
when CDC is confirmed, re-runs the full signal build to generate an
AISignal and trigger activation.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from celery import shared_task
from loguru import logger
from sqlalchemy import select

from app.core.constants import TF_FALLBACK_CHAIN, cdc_for
from app.models.ai_scan import AIWatchlistItem, AILatestScan
from app.models.ai_signal import AISignal
from app.services.ai_scanner import build_signal, fetch_ohlcv, htf_for, signal_to_dict, to_ccxt
from app.services.cache import sync_redis
from app.services.confirmation_scanner import (
    check_ltf_cdc,
    get_watchlist,
    remove_from_watchlist,
)
from app.services.database import SessionLocal


@shared_task(
    bind=True,
    max_retries=1,
    name="app.tasks.confirmation_scan_task.scan_confirmation_watchlist",
    queue="default",
)
def scan_confirmation_watchlist(self):
    """Poll Redis watchlist and promote confirmed setups to AISignal."""
    try:
        return _run_confirmation_scan()
    except Exception as exc:
        logger.error(f"[CONFIRMATION SCAN] Fatal error: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60)


def _run_async(coro):
    """Run async coroutine reusing the thread-local loop if available."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _run_confirmation_scan() -> dict:
    items = get_watchlist(sync_redis)
    if not items:
        return {"status": "no_watchlist_items", "promoted": 0}

    logger.info(f"[CONFIRMATION SCAN] {len(items)} setups in watchlist")

    # Fetch CDC timeframe OHLCV for all watched items concurrently
    async def _fetch_ltf_all():
        sem = asyncio.Semaphore(3)
        tasks = []
        cdc_tfs = {}
        keys = []
        for item in items:
            sym = item["symbol"]
            tf = item["timeframe"]
            cdc_tf = cdc_for(tf) or "5m"
            key = (sym, tf)
            cdc_tfs[key] = cdc_tf
            keys.append(key)
            tasks.append(fetch_ohlcv(sym, cdc_tf, sem))
        results = await asyncio.gather(*tasks)
        return {key: ohlcv for key, (_, ohlcv) in zip(keys, results)}, cdc_tfs

    ltf_map, cdc_tfs = _run_async(_fetch_ltf_all())

    promoted = 0
    for item in items:
        sym = item["symbol"]
        direction = item["direction"]
        tf = item["timeframe"]
        key = (sym, tf)
        ltf_ohlcv = ltf_map.get(key)

        if not ltf_ohlcv or len(ltf_ohlcv) < 30:
            logger.debug(f"[CONFIRMATION SCAN] {sym}/{tf}: insufficient LTF data")
            continue

        # Check CDC in adaptive LTF
        cdc_tf = cdc_tfs.get(key, "5m")
        cdc_confirmed = check_ltf_cdc(ltf_ohlcv, direction)
        if not cdc_confirmed:
            logger.debug(f"[CONFIRMATION SCAN] {sym}/{tf} {direction}: no CDC yet")
            continue

        logger.info(f"[CONFIRMATION SCAN] {sym}/{tf} {direction}: CDC confirmed in {cdc_tf}")

        # Re-fetch main TF OHLCV and rebuild signal with fresh data
        try:
            _, main_ohlcv = _run_async(fetch_ohlcv(sym, tf))
            if not main_ohlcv or len(main_ohlcv) < 50:
                logger.warning(f"[CONFIRMATION SCAN] {sym}/{tf}: insufficient main TF data")
                remove_from_watchlist(sync_redis, sym, direction, tf)
                continue

            htf = htf_for(tf)
            htf_ohlcv = None
            if htf:
                _, htf_ohlcv = _run_async(fetch_ohlcv(sym, htf))

            result_dict, sig = build_signal(sym, tf, main_ohlcv, htf_ohlcv=htf_ohlcv)

            if sig is None:
                logger.info(f"[CONFIRMATION SCAN] {sym}/{tf}: setup no longer valid")
                remove_from_watchlist(sync_redis, sym, direction, tf)
                continue

            # Mark as CDC-confirmed
            feat = dict(sig.features or {})
            feat["ltf_cdc_confirmed"] = True
            feat["cdc_confirmed_at"] = datetime.now(timezone.utc).isoformat()
            sig.features = feat

            with SessionLocal() as db:
                # Dedup
                existing = db.execute(
                    select(AISignal.id).where(
                        AISignal.ticker == sig.ticker,
                        AISignal.timeframe == sig.timeframe,
                        AISignal.direction == sig.direction,
                        AISignal.signal_time == sig.signal_time,
                    ).limit(1)
                ).first()
                if existing:
                    logger.info(f"[CONFIRMATION SCAN] {sym}/{tf}: dedup — signal already exists")
                    remove_from_watchlist(sync_redis, sym, direction, tf)
                    continue

                db.add(sig)
                db.commit()
                db.refresh(sig)
                promoted += 1
                logger.info(
                    f"[CONFIRMATION SCAN] {sym}/{tf}: PROMOTED → signal {sig.id} "
                    f"score={sig.score:.1f}"
                )

                # Update latest scan
                _upsert_latest_scan_sync(db, sym, tf, result_dict, sig)

                # Activate
                from app.tasks.bot_activator_task import activate_signal
                activate_signal.delay(str(sig.id))

                # LLM diagnosis
                try:
                    from app.tasks.llm_tasks import generate_signal_diagnosis
                    generate_signal_diagnosis.delay(str(sig.id), "anti_fake")
                except Exception:
                    pass

            remove_from_watchlist(sync_redis, sym, direction, tf)

        except Exception as exc:
            logger.error(f"[CONFIRMATION SCAN] {sym}/{tf}: error promoting signal: {exc}")
            continue

    logger.info(f"[CONFIRMATION SCAN] promoted={promoted}")
    return {"status": "ok", "watched": len(items), "promoted": promoted}


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
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models.ai_scan import AILatestScan
    stmt = pg_insert(AILatestScan).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "timeframe"],
        set_={k: v for k, v in values.items() if k not in ("symbol", "timeframe")},
    )
    db.execute(stmt)
    db.commit()
