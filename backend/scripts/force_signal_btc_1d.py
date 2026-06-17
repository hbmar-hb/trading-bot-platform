#!/usr/bin/env python3
"""
Force-generate a signal for BTC/USDT 1d using the real pipeline,
save it to DB, and verify forward_levels + support_levels are present.

Usage: cd backend && python scripts/force_signal_btc_1d.py
"""
import sys, asyncio, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://admin:Capnegret240323@localhost:5433/tradingbot")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://admin:Capnegret240323@localhost:5433/tradingbot")

from datetime import datetime, timezone
from loguru import logger
import ccxt.async_support as ccxt

from app.services.ai_scanner import build_signal
from app.services.database import SessionLocal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.ai_scan import AILatestScan


async def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200):
    exchange = ccxt.bingx({"options": {"defaultType": "swap"}})
    ccxt_sym = f"{symbol}/USDT:USDT"
    ohlcv = await exchange.fetch_ohlcv(ccxt_sym, timeframe, limit=limit)
    await exchange.close()
    return ohlcv


def save_signal_to_db(sig):
    """Save AISignal to DB and upsert ai_latest_scans."""
    from app.services.ai_scanner import signal_to_dict
    
    with SessionLocal() as db:
        db.add(sig)
        db.commit()
        db.refresh(sig)
        
        # Upsert latest scan
        result_dict = {"symbol": sig.ticker, "status": "SIGNAL", "context": {}}
        values = {
            "symbol": sig.ticker,
            "timeframe": sig.timeframe,
            "status": "SIGNAL",
            "context": {},
            "signal_data": signal_to_dict(sig),
            "signal_id": sig.id,
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
        db.commit()
        
        return sig.id


def main():
    print("=" * 70)
    print("FORCE SIGNAL: BTC/USDT 1d")
    print("=" * 70)
    
    symbol = "BTCUSDT"
    timeframe = "1d"
    
    print(f"\n1. Fetching OHLCV for {symbol}/{timeframe}...")
    ohlcv = asyncio.run(fetch_ohlcv("BTC", "1d", limit=200))
    print(f"   Fetched {len(ohlcv)} candles")
    
    print(f"\n2. Building signal...")
    result_dict, sig = build_signal(symbol, timeframe, ohlcv)
    
    print(f"   Status: {result_dict['status']}")
    
    if sig is None:
        print(f"   ❌ No signal generated")
        print(f"   Context: {result_dict.get('context')}")
        return
    
    print(f"\n3. Signal generated:")
    print(f"   Direction: {sig.direction}")
    print(f"   Score: {sig.score}")
    print(f"   Entry: {sig.entry_price}")
    print(f"   SL: {sig.stop_loss}")
    print(f"   TP1: {sig.take_profit_1}")
    print(f"   TP2: {sig.take_profit_2}")
    
    features = sig.features or {}
    forward_levels = features.get("forward_levels", [])
    support_levels = features.get("support_levels", [])
    
    print(f"\n4. Structural levels in features:")
    print(f"   Forward levels: {len(forward_levels)}")
    for lvl in forward_levels[:5]:
        print(f"      → {lvl['kind']} @ {lvl['price']:.2f} ({lvl['distance_pct']:.3f}%)")
    print(f"   Support levels: {len(support_levels)}")
    for lvl in support_levels[:5]:
        print(f"      → {lvl['kind']} @ {lvl['price']:.2f} ({lvl['distance_pct']:.3f}%)")
    
    print(f"   tp1_source: {features.get('tp1_source')}")
    print(f"   tp2_source: {features.get('tp2_source')}")
    print(f"   tp1_distance_r: {features.get('tp1_distance_r')}")
    print(f"   tp1_strength: {features.get('tp1_strength')}")
    print(f"   forward_density: {features.get('forward_density')}")
    
    print(f"\n5. Saving to DB...")
    sig_id = save_signal_to_db(sig)
    print(f"   ✅ Saved signal ID: {sig_id}")
    
    print(f"\n6. Validation:")
    checks = [
        ("Signal generated", True),
        ("Forward levels present", len(forward_levels) > 0),
        ("Support levels present", len(support_levels) > 0),
        ("TP1 is structural", features.get("tp1_source") != "fallback_1.5R"),
    ]
    for name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"   {status} {name}")
    
    all_passed = all(p for _, p in checks)
    print(f"\n{'='*70}")
    if all_passed:
        print("✅ FORCE SIGNAL TEST PASSED")
    else:
        print("❌ FORCE SIGNAL TEST FAILED")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
