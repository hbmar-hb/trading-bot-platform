#!/usr/bin/env python3
"""
End-to-end pipeline test with REAL market data for FARTCOIN/USDT 1d.
Verifies that ICT engine produces forward_levels and support_levels,
and confluence engine propagates them.

Usage: cd backend && python scripts/test_real_signal_pipeline.py
"""
import sys, asyncio, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://admin:Capnegret240323@localhost:5433/tradingbot")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://admin:Capnegret240323@localhost:5433/tradingbot")

from app.core.ict_engine import analyze as ict_analyze
from app.engines.confluence_engine import analyze_confluence
import ccxt.async_support as ccxt


async def fetch_candles(ticker: str, timeframe: str, limit: int = 200):
    client = ccxt.bingx({"options": {"defaultType": "swap"}})
    symbol = f"{ticker}/USDT:USDT"
    ohlcv = await client.fetch_ohlcv(symbol, timeframe, limit=limit)
    await client.close()
    return [
        {"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
        for c in ohlcv
    ]


def main():
    print("=" * 60)
    print("TEST: Real market data pipeline")
    print("=" * 60)

    ticker = "FARTCOIN"
    timeframe = "1d"
    print(f"Fetching data for {ticker}/{timeframe}...")
    
    # Run async data fetch
    candles = asyncio.run(fetch_candles(ticker, timeframe, limit=200))
    print(f"Fetched {len(candles)} candles")
    if len(candles) < 50:
        print("Not enough data")
        return

    last = candles[-1]
    print(f"Latest candle: O={last['open']} H={last['high']} L={last['low']} C={last['close']}")

    print("\n--- ICT Engine ---")
    ict = ict_analyze(candles, pivot_len=5, atr_mult=0.3, atr_len=14, entry_mode="ob_or_fvg")
    print(f"Signal: {ict.signal}, Bias: {ict.bias}, Grade: {ict.grade}")
    print(f"Entry zone: {ict.entry_zone}")
    print(f"Forward levels: {len(ict.forward_levels)}")
    for lvl in ict.forward_levels[:8]:
        print(f"  → {lvl.kind} @ {lvl.price:.4f} ({lvl.distance_pct:.3f}%)")
    print(f"Support levels: {len(ict.support_levels)}")
    for lvl in ict.support_levels[:8]:
        print(f"  → {lvl.kind} @ {lvl.price:.4f} ({lvl.distance_pct:.3f}%)")

    print("\n--- Confluence Engine ---")
    confluence = analyze_confluence(candles, ticker, timeframe)
    if confluence is None:
        print("Confluence returned None (no setup)")
        return

    print(f"Direction: {confluence.direction}")
    print(f"Score: {confluence.score}")
    print(f"Entry: {confluence.entry_price}")
    print(f"SL: {confluence.stop_loss}")
    print(f"TP1: {confluence.take_profit_1} (source: {confluence.features.get('tp1_source')})")
    print(f"TP2: {confluence.take_profit_2} (source: {confluence.features.get('tp2_source')})")
    print(f"TP1 close %: {confluence.tp1_close_pct}")
    print(f"Forward levels in features: {len(confluence.features.get('forward_levels', []))}")
    print(f"Support levels in features: {len(confluence.features.get('support_levels', []))}")
    print(f"tp1_distance_r: {confluence.features.get('tp1_distance_r')}")
    print(f"tp1_strength: {confluence.features.get('tp1_strength')}")
    print(f"forward_density: {confluence.features.get('forward_density')}")
    print(f"R:R: {confluence.risk_reward}")

    # Validation checks
    print("\n--- Validation ---")
    errors = []
    if ict.signal == "none":
        errors.append("ICT signal is 'none'")
    if len(ict.forward_levels) == 0:
        errors.append("No forward_levels from ICT")
    if len(ict.support_levels) == 0:
        errors.append("No support_levels from ICT")
    if confluence.tp1_source == "fallback_1.5R":
        errors.append("Confluence using fallback TP1 (expected structural)")
    
    fwd = confluence.features.get("forward_levels", [])
    if fwd:
        strengths = {"eq_high": 1.0, "eq_low": 1.0, "fvg_bear": 0.7, "fvg_bull": 0.7}
        for i in range(len(fwd)-1):
            s0 = strengths.get(fwd[i]["kind"], 0.5)
            s1 = strengths.get(fwd[i+1]["kind"], 0.5)
            if s0 < s1:
                errors.append(f"Forward levels not sorted by strength at index {i}")
                break

    sup = confluence.features.get("support_levels", [])
    if sup:
        strengths = {"eq_high": 1.0, "eq_low": 1.0, "fvg_bear": 0.7, "fvg_bull": 0.7}
        for i in range(len(sup)-1):
            s0 = strengths.get(sup[i]["kind"], 0.5)
            s1 = strengths.get(sup[i+1]["kind"], 0.5)
            if s0 < s1:
                errors.append(f"Support levels not sorted by strength at index {i}")
                break

    if errors:
        print("❌ FAILURES:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("✅ All validations passed!")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
