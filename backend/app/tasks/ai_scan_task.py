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
from datetime import datetime, timezone

from celery import shared_task
from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.services.database import SessionLocal
from app.models.ai_scan import AIWatchlistItem, AILatestScan
from app.services.ai_scanner import (
    build_signal, fetch_ohlcv, htf_for, signal_to_dict,
)


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


def _run_scan() -> dict:
    # ── 1. Read watchlist (sync DB) ───────────────────────────
    with SessionLocal() as db:
        rows = db.execute(
            select(AIWatchlistItem.symbol, AIWatchlistItem.timeframe).distinct()
        ).all()

    if not rows:
        return {"status": "no_watchlist_items"}

    pairs     = list({(r.symbol, r.timeframe) for r in rows})
    htf_pairs = list({(sym, htf_for(tf)) for sym, tf in pairs if htf_for(tf)})

    # ── 2. Fetch OHLCV concurrently (pure async, no DB) ───────
    async def _fetch_all():
        sem = asyncio.Semaphore(6)
        return await asyncio.gather(
            *[fetch_ohlcv(sym, tf,  sem) for sym, tf  in pairs],
            *[fetch_ohlcv(sym, htf, sem) for sym, htf in htf_pairs],
        )

    all_fetches = asyncio.run(_fetch_all())

    ltf_fetches = all_fetches[:len(pairs)]
    htf_cache: dict[tuple[str, str], list | None] = {
        (sym, htf): ohlcv
        for (sym, htf), (_, ohlcv) in zip(htf_pairs, all_fetches[len(pairs):])
    }

    # ── 3. Analyse + write results (sync DB) ──────────────────
    signals = 0
    with SessionLocal() as db:
        for (sym, tf), (_, ohlcv) in zip(pairs, ltf_fetches):
            if not ohlcv or len(ohlcv) < 50:
                continue

            htf      = htf_for(tf)
            htf_ohlcv = htf_cache.get((sym, htf)) if htf else None
            result_dict, sig = build_signal(sym, tf, ohlcv, htf_ohlcv=htf_ohlcv)

            if sig:
                db.add(sig)
                db.commit()
                db.refresh(sig)
                _upsert_latest_scan_sync(db, sym, tf, result_dict, sig)
                signals += 1
                from app.tasks.bot_activator_task import activate_signal
                activate_signal.delay(str(sig.id))
            else:
                _upsert_latest_scan_sync(db, sym, tf, result_dict)

        db.commit()

    logger.info(f"[AI SCAN] scanned={len(pairs)} signals={signals}")
    return {"status": "ok", "scanned": len(pairs), "signals": signals}


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
