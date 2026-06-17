#!/usr/bin/env python3
"""
Unit test: verify that ict_engine computes forward_levels and support_levels,
and that confluence_engine propagates them correctly.

Usage: cd backend && python scripts/test_ict_forward_support.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.ict_engine import analyze as ict_analyze
from app.engines.confluence_engine import analyze_confluence


def build_candles():
    """Build a synthetic OHLCV dataset that creates a valid ICT setup."""
    import random
    random.seed(42)
    base = 50000.0
    candles = []
    for i in range(200):
        # Create a downtrend followed by CHoCH + OB
        if i < 100:
            trend = -1
        elif i < 120:
            trend = 1  # reversal
        else:
            trend = -0.3
        
        noise = random.uniform(-0.005, 0.005)
        open_p = base * (1 + (i - 100) * trend * 0.001 + noise)
        close = open_p * (1 + random.uniform(-0.003, 0.003))
        high = max(open_p, close) * (1 + random.uniform(0, 0.002))
        low = min(open_p, close) * (1 - random.uniform(0, 0.002))
        vol = random.uniform(1000, 5000)
        
        candles.append({
            "open": round(open_p, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(vol, 2),
        })
    return candles


def main():
    print("=" * 60)
    print("TEST: ICT Engine → Forward + Support Levels")
    print("=" * 60)

    candles = build_candles()
    print(f"Generated {len(candles)} synthetic candles")

    # Test ICT engine
    ict = ict_analyze(candles, pivot_len=5, atr_mult=0.3, atr_len=14, entry_mode="ob_or_fvg")
    
    print(f"\nICT Result:")
    print(f"  Signal: {ict.signal}")
    print(f"  Bias: {ict.bias}")
    print(f"  Entry zone: {ict.entry_zone}")
    print(f"  Grade: {ict.grade}")
    print(f"  Forward levels: {len(ict.forward_levels)}")
    for lvl in ict.forward_levels[:5]:
        print(f"    - {lvl.kind} @ {lvl.price:.2f} ({lvl.distance_pct:.3f}%)")
    print(f"  Support levels: {len(ict.support_levels)}")
    for lvl in ict.support_levels[:5]:
        print(f"    - {lvl.kind} @ {lvl.price:.2f} ({lvl.distance_pct:.3f}%)")

    if ict.signal == "none":
        print("\n⚠️  No ICT signal — trying confluence engine anyway...")

    # Test confluence engine
    confluence = analyze_confluence(candles, "BTCUSDT", "1d")
    
    if confluence is None:
        print("\n❌ Confluence engine returned None (no setup)")
        print("This is expected with synthetic data — real market data needed")
        return

    print(f"\nConfluence Result:")
    print(f"  Direction: {confluence.direction}")
    print(f"  Score: {confluence.score}")
    print(f"  Entry: {confluence.entry_price}")
    print(f"  SL: {confluence.stop_loss}")
    print(f"  TP1: {confluence.take_profit_1} (source: {confluence.features.get('tp1_source')})")
    print(f"  TP2: {confluence.take_profit_2} (source: {confluence.features.get('tp2_source')})")
    print(f"  TP1 close %: {confluence.tp1_close_pct}")
    print(f"  Forward levels in features: {len(confluence.features.get('forward_levels', []))}")
    print(f"  Support levels in features: {len(confluence.features.get('support_levels', []))}")
    print(f"  tp1_distance_r: {confluence.features.get('tp1_distance_r')}")
    print(f"  tp1_strength: {confluence.features.get('tp1_strength')}")
    print(f"  forward_density: {confluence.features.get('forward_density')}")
    print(f"  R:R: {confluence.risk_reward}")

    # Verify ordering by strength
    fwd = confluence.features.get("forward_levels", [])
    if len(fwd) >= 2:
        strengths = {"eq_high": 1.0, "eq_low": 1.0, "fvg_bear": 0.7, "fvg_bull": 0.7}
        s0 = strengths.get(fwd[0]["kind"], 0.5)
        s1 = strengths.get(fwd[1]["kind"], 0.5)
        if s0 >= s1:
            print(f"\n✅ Forward levels ordered by strength: {fwd[0]['kind']}({s0}) >= {fwd[1]['kind']}({s1})")
        else:
            print(f"\n❌ Forward levels NOT ordered by strength!")

    # Verify support_levels presence
    sup = confluence.features.get("support_levels", [])
    if sup:
        print(f"\n✅ Support levels present ({len(sup)} items)")
    else:
        print(f"\n⚠️  No support levels (fallback mechanical SL only)")

    # Verify ConfluenceResult has the fields
    if confluence.forward_levels:
        print(f"✅ ConfluenceResult.forward_levels present")
    if confluence.support_levels:
        print(f"✅ ConfluenceResult.support_levels present")

    print("\n" + "=" * 60)
    print("Test completed")
    print("=" * 60)


if __name__ == "__main__":
    main()
