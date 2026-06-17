#!/usr/bin/env python3
"""Recalculate SMC macro context (Fase A) for historical AI signals.

The scanner was accidentally overwriting `features["macro_context"]` with the
funding/news gate context, so historical signals lack NWOG/ORG/BISI/SIBI/IFVG
features.  This script re-downloads the required HTF/LTF candles and updates
`macro_context` + `macro_bonus` in place.

Run inside the backend container:
    python scripts/recalculate_smc_macro_context.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running from any cwd
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Silence verbose macro-engine logs
os.environ.setdefault("LOGURU_LEVEL", "WARNING")

import ccxt
from loguru import logger

from app.core.ict_engine import analyze as ict_analyze
from app.engines.smc_macro_engine import build_macro_features
from app.models.ai_signal import AISignal
from app.services.database import SessionLocal
from app.core.constants import TF_SECONDS

_BATCH_SIZE = 500
_SLEEP_BETWEEN_CALLS = 0.1


def _signal_to_ccxt(symbol: str) -> str:
    """Best-effort ccxt symbol conversion (matches ai_scanner.to_ccxt)."""
    if "/" in symbol:
        # Fix malformed symbols like BTCUSDT/USDT:USDT -> BTC/USDT:USDT
        if symbol.endswith("/USDT:USDT") and not symbol.startswith("BTC/"):
            symbol = symbol.replace("USDT/USDT:USDT", "USDT", 1)
        return symbol
    s = symbol.replace(".P", "").replace(".p", "")
    for q in ["USDT", "USDC", "BTC", "ETH", "USD"]:
        if s.endswith(q):
            return f"{s[:-len(q)]}/{q}:{q}"
    return symbol


def _fetch_range(
    exchange: ccxt.binance,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
    limit: int = 1000,
) -> list[list]:
    """Fetch OHLCV between since_ms and until_ms, paginating if needed."""
    all_candles: list[list] = []
    current_since = since_ms
    while current_since < until_ms:
        try:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=limit)
        except Exception as exc:
            logger.warning(f"[MacroRecalc] fetch {symbol}/{timeframe} failed: {exc}")
            break
        if not candles:
            break
        all_candles.extend(c for c in candles if c[0] <= until_ms)
        if len(candles) < limit:
            break
        current_since = candles[-1][0] + 1
        time.sleep(_SLEEP_BETWEEN_CALLS)
    return all_candles


def _closed_dicts(candles: list[list]) -> list[dict]:
    return [
        {"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])}
        for c in candles
    ]


def _build_bonus(macro: dict) -> float:
    bonus = 0.0
    if macro.get("nwog_aligned"):
        bonus += 15.0
    if macro.get("org_aligned"):
        bonus += 12.0
    if macro.get("bisi_present") or macro.get("sibi_present"):
        bonus += 12.0
    if macro.get("ifvg_present"):
        bonus += 8.0
    return bonus


def recalculate() -> dict:
    exchange = ccxt.binance({"options": {"defaultType": "swap"}})
    db = SessionLocal()
    try:
        signals = (
            db.query(AISignal)
            .filter(AISignal.features.isnot(None))
            .filter(AISignal.entry_price.isnot(None))
            .all()
        )
        logger.info(f"[MacroRecalc] Loaded {len(signals)} signals with features")

        by_tf: dict[tuple[str, str], list[AISignal]] = {}
        for sig in signals:
            sym = sig.ccxt_symbol or _signal_to_ccxt(sig.ticker)
            by_tf.setdefault((sym, sig.timeframe), []).append(sig)

        by_symbol: dict[str, list[AISignal]] = {}
        for sig in signals:
            sym = sig.ccxt_symbol or _signal_to_ccxt(sig.ticker)
            by_symbol.setdefault(sym, []).append(sig)

        daily_cache: dict[str, list[list]] = {}
        weekly_cache: dict[str, list[list]] = {}
        for sym, sigs in by_symbol.items():
            times = [s.signal_time for s in sigs if s.signal_time]
            if not times:
                continue
            min_t = min(times)
            max_t = max(times)
            since_d = int((min_t - timedelta(days=90)).timestamp() * 1000)
            until_d = int((max_t + timedelta(days=1)).timestamp() * 1000)
            logger.info(f"[MacroRecalc] Fetching 1d for {sym} ({len(sigs)} signals)")
            daily_cache[sym] = _fetch_range(exchange, sym, "1d", since_d, until_d)

            since_w = int((min_t - timedelta(days=400)).timestamp() * 1000)
            until_w = int((max_t + timedelta(days=7)).timestamp() * 1000)
            logger.info(f"[MacroRecalc] Fetching 1w for {sym} ({len(sigs)} signals)")
            weekly_cache[sym] = _fetch_range(exchange, sym, "1w", since_w, until_w)

        updated = 0
        skipped = 0
        errors = 0

        for (sym, tf), sigs in by_tf.items():
            times = [s.signal_time for s in sigs if s.signal_time]
            if not times:
                continue
            tf_secs = TF_SECONDS.get(tf, 3600)
            min_t = min(times)
            max_t = max(times)
            since_tf = int((min_t - timedelta(seconds=tf_secs * 250)).timestamp() * 1000)
            until_tf = int((max_t + timedelta(seconds=tf_secs)).timestamp() * 1000)
            logger.info(f"[MacroRecalc] Fetching {tf} for {sym} ({len(sigs)} signals)")
            tf_candles = _fetch_range(exchange, sym, tf, since_tf, until_tf)
            if len(tf_candles) < 60:
                logger.warning(f"[MacroRecalc] Insufficient {tf} data for {sym}; skipping {len(sigs)} signals")
                skipped += len(sigs)
                continue

            for sig in sorted(sigs, key=lambda s: s.signal_time or datetime.min.replace(tzinfo=timezone.utc)):
                try:
                    if not sig.signal_time:
                        skipped += 1
                        continue
                    ts_ms = int(sig.signal_time.timestamp() * 1000)
                    ltf_candles = [c for c in tf_candles if c[0] <= ts_ms]
                    if len(ltf_candles) < 50:
                        skipped += 1
                        continue
                    closed = _closed_dicts(ltf_candles[:-1])
                    if len(closed) < 50:
                        skipped += 1
                        continue

                    ict = ict_analyze(closed)
                    entry_mid = float(sig.entry_price)
                    pd_position = float((sig.features or {}).get("pd_position", 0.5))

                    d1_candles = [c for c in daily_cache.get(sym, []) if c[0] <= ts_ms]
                    w1_candles = [c for c in weekly_cache.get(sym, []) if c[0] <= ts_ms]

                    macro = build_macro_features(
                        candles_1d=d1_candles,
                        candles_1w=w1_candles,
                        ict_ltf=ict,
                        entry_mid=entry_mid,
                        direction=sig.direction,
                        pd_position=pd_position,
                        candles_ltf=closed,
                    )

                    features = dict(sig.features or {})
                    features["macro_context"] = macro
                    features["macro_bonus"] = round(_build_bonus(macro), 1)
                    sig.features = features
                    db.add(sig)
                    updated += 1

                    if updated % _BATCH_SIZE == 0:
                        db.commit()
                        logger.info(f"[MacroRecalc] Committed {updated}/{len(signals)} updates")
                except Exception as exc:
                    logger.warning(f"[MacroRecalc] Signal {sig.id} failed: {exc}")
                    errors += 1
                    skipped += 1

        db.commit()
        return {"updated": updated, "skipped": skipped, "errors": errors}
    finally:
        db.close()


if __name__ == "__main__":
    result = recalculate()
    logger.info(f"[MacroRecalc] Done: {result}")
    print(result)
