#!/usr/bin/env python3
"""Recalculate historical AI signal outcomes with Fase C execution model.

Optimized version: fetches OHLCV once per (symbol, timeframe) range and
reuses it for all signals in that group.  Much faster than one fetch per
signal.

Usage (inside backend container):
    python scripts/recalculate_signal_outcomes.py --since-days 90 --dry-run
    python scripts/recalculate_signal_outcomes.py --since-days 90
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ccxt.async_support as ccxt
from loguru import logger
from sqlalchemy import select, update

from app.engines.realistic_outcome_engine import simulate_outcome
from app.models.ai_signal import AISignal
from app.models.llm_signal_diagnosis import LLMSignalDiagnosis
from app.services.database import SessionLocal
from app.tasks.ai_outcome_tracker import _evaluate_outcome


_TF_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1w": 604800,
}

_BINANCE_LIMIT = 1000


async def _fetch_range(exchange: ccxt.Exchange, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> list:
    """Fetch all candles for a symbol/timeframe between since_ms and until_ms."""
    candles: list = []
    current_since = since_ms
    while current_since < until_ms:
        try:
            batch = await exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=_BINANCE_LIMIT)
        except Exception as exc:
            logger.warning(f"[RECALC] Fetch error {symbol}/{timeframe}: {exc}")
            break
        if not batch:
            break
        candles.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= current_since:
            break
        current_since = last_ts + 1
    return candles


def _candles_after(candles: list, signal_ts_ms: int) -> list:
    return [c for c in candles if c[0] > signal_ts_ms]


def _recalculate_one(sig: AISignal, candles_after: list) -> dict:
    ideal_outcome, ideal_pnl, ideal_bars, failure_type = _evaluate_outcome(sig, candles_after)
    realistic = simulate_outcome(sig, candles_after)
    return {
        "outcome": ideal_outcome,
        "pnl_pct": ideal_pnl,
        "outcome_bars": ideal_bars,
        "failure_type": failure_type,
        "realistic_outcome": realistic.outcome,
        "realistic_pnl_pct": realistic.pnl_pct,
    }


def _load_signals(db, since: datetime, ticker: str | None = None) -> list[AISignal]:
    q = select(AISignal).where(
        AISignal.outcome != "PENDING",
        AISignal.created_at >= since,
    )
    if ticker:
        q = q.where(AISignal.ticker == ticker.upper())
    q = q.order_by(AISignal.signal_time)
    return list(db.execute(q).scalars().all())


def _group_signals(signals: list[AISignal]) -> dict[tuple[str, str], list[AISignal]]:
    groups: dict[tuple[str, str], list[AISignal]] = defaultdict(list)
    for sig in signals:
        groups[(sig.ccxt_symbol, sig.timeframe)].append(sig)
    return groups


async def _run(args: argparse.Namespace) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    with SessionLocal() as db:
        signals = _load_signals(db, since, args.ticker)

    total = len(signals)
    logger.info(f"[RECALC] Loaded {total} resolved signals since {since.isoformat()}")
    if total == 0:
        return {"checked": 0, "updated": 0, "errors": 0}

    groups = _group_signals(signals)
    logger.info(f"[RECALC] {len(groups)} unique (symbol, timeframe) groups")

    exchange = ccxt.binance({"options": {"defaultType": "swap"}})
    updated = 0
    errors = 0
    unchanged = 0
    processed = 0
    until_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    try:
        for (symbol, tf), group_signals in groups.items():
            group_signals.sort(key=lambda s: s.signal_time)
            min_signal_time = min(s.signal_time for s in group_signals)
            since_ms = int(min_signal_time.timestamp() * 1000)

            logger.info(
                f"[RECALC] Fetching {symbol}/{tf} range "
                f"{min_signal_time.isoformat()} → now ({len(group_signals)} signals)"
            )
            candles = await _fetch_range(exchange, symbol, tf, since_ms, until_ms)
            if not candles:
                logger.warning(f"[RECALC] No candles for {symbol}/{tf}, skipping group")
                continue

            for sig in group_signals:
                processed += 1
                try:
                    sig_ts_ms = int(sig.signal_time.timestamp() * 1000)
                    candles_after = _candles_after(candles, sig_ts_ms)
                    if not candles_after:
                        logger.info(f"[RECALC] {processed}/{total} {sig.id}: no candles, skipped")
                        continue

                    new = _recalculate_one(sig, candles_after)

                    old_ideal = sig.outcome
                    old_real = sig.realistic_outcome
                    changed = (
                        old_ideal != new["outcome"]
                        or old_real != new["realistic_outcome"]
                        or sig.realistic_pnl_pct != new["realistic_pnl_pct"]
                    )

                    logger.info(
                        f"[RECALC] {processed}/{total} {sig.ticker}/{sig.timeframe} "
                        f"{sig.id}: ideal {old_ideal}->{new['outcome']} "
                        f"real {old_real}->{new['realistic_outcome']} "
                        f"pnl={new['realistic_pnl_pct']}"
                    )

                    if args.dry_run:
                        continue

                    with SessionLocal() as db:
                        s = db.get(AISignal, sig.id)
                        if not s:
                            logger.warning(f"[RECALC] {sig.id}: signal disappeared, skipped")
                            continue

                        # Fase C: never write None into non-nullable columns.  If the
                        # ideal evaluator could not resolve within the candle window,
                        # keep the existing ideal label or mark as INCONCLUSIVE.
                        if new["outcome"] is not None:
                            s.outcome = new["outcome"]
                        elif new["realistic_outcome"] == "INCONCLUSIVE":
                            s.outcome = "INCONCLUSIVE"
                        s.pnl_pct = new["pnl_pct"]
                        s.outcome_bars = new["outcome_bars"]
                        if s.resolved_at is None:
                            s.resolved_at = datetime.now(timezone.utc)
                        s.realistic_outcome = new["realistic_outcome"]
                        s.realistic_pnl_pct = new["realistic_pnl_pct"]

                        feat = dict(s.features or {})
                        if new["failure_type"]:
                            feat["failure_type"] = new["failure_type"]
                        elif "failure_type" in feat:
                            del feat["failure_type"]
                        s.features = feat

                        db.commit()

                        llm_outcome = new["realistic_outcome"] if new["realistic_outcome"] is not None else new["outcome"]
                        llm_pnl = new["realistic_pnl_pct"] if new["realistic_pnl_pct"] is not None else new["pnl_pct"]
                        db.execute(
                            update(LLMSignalDiagnosis)
                            .where(LLMSignalDiagnosis.ai_signal_id == sig.id)
                            .values(outcome=llm_outcome, pnl_pct=llm_pnl, resolved_at=s.resolved_at)
                        )
                        db.commit()

                    updated += 1
                    if not changed:
                        unchanged += 1
                except Exception as exc:
                    errors += 1
                    logger.error(f"[RECALC] {sig.id} error: {exc}")
                    if args.raise_on_error:
                        raise
    finally:
        await exchange.close()

    logger.info(
        f"[RECALC] Done. total={total} updated={updated} unchanged={unchanged} errors={errors}"
    )
    return {"checked": total, "updated": updated, "unchanged": unchanged, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Recalculate historical AI signal outcomes")
    parser.add_argument("--since-days", type=int, default=90, help="How far back to recalculate")
    parser.add_argument("--ticker", type=str, default=None, help="Limit to one ticker")
    parser.add_argument("--dry-run", action="store_true", help="Print changes but do not write")
    parser.add_argument("--raise-on-error", action="store_true", help="Stop on first error")
    args = parser.parse_args()

    result = asyncio.run(_run(args))
    print(result)


if __name__ == "__main__":
    main()
