#!/usr/bin/env python3
"""
End-to-end test: ICT → Confluence → BotActivator (simulated) → TrailingWorker (simulated)

Uses REAL BTC/USDT 1d data to generate a signal, then simulates how trailing_worker
would behave as price moves.

Usage: cd backend && python scripts/test_end_to_end_structural_sl.py
"""
import sys, asyncio, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://admin:Capnegret240323@localhost:5433/tradingbot")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://admin:Capnegret240323@localhost:5433/tradingbot")

from decimal import Decimal
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


def simulate_trailing_worker(position_extra, entry_price, current_price, side, initial_risk_pct, bot_dynamic_sl_config):
    """
    Simulates the structural + mechanical SL logic from trailing_worker.py
    Returns: (dynamic_sl, chosen_source)
    """
    from decimal import Decimal
    from app.core.risk_manager import calculate_dynamic_sl_price

    extra = position_extra
    dy_cfg = bot_dynamic_sl_config or {}
    
    if not dy_cfg.get("enabled"):
        return None, "disabled"
    
    current_price = Decimal(str(current_price))
    entry_price = Decimal(str(entry_price))
    _STRUCTURAL_MARGIN = Decimal("0.005")
    
    structural_sl = None
    support_levels = extra.get("support_levels", [])
    
    if support_levels:
        if side == "long":
            structural_candidates = [
                Decimal(str(l["price"]))
                for l in support_levels
                if current_price > Decimal(str(l["price"])) * (Decimal("1") + _STRUCTURAL_MARGIN)
            ]
            if structural_candidates:
                structural_sl = max(structural_candidates)
        else:
            structural_candidates = [
                Decimal(str(l["price"]))
                for l in support_levels
                if current_price < Decimal(str(l["price"])) * (Decimal("1") - _STRUCTURAL_MARGIN)
            ]
            if structural_candidates:
                structural_sl = min(structural_candidates)
    
    # Mechanical SL
    mechanical_sl = None
    if initial_risk_pct > 0:
        step_r = Decimal(str(dy_cfg.get("step_r", dy_cfg.get("step_percent", 0.5))))
        max_steps = int(dy_cfg.get("max_steps", 0))
        try:
            mechanical_sl = calculate_dynamic_sl_price(
                entry_price=entry_price,
                current_price=current_price,
                side=side,
                step_r=step_r,
                max_steps=max_steps,
                initial_risk_pct=Decimal(str(initial_risk_pct)),
                leverage=None,
                use_roi=False,
            )
        except Exception:
            mechanical_sl = None
    
    # Hybrid
    if structural_sl is not None and mechanical_sl is not None:
        if side == "long":
            dynamic_sl = max(structural_sl, mechanical_sl)
        else:
            dynamic_sl = min(structural_sl, mechanical_sl)
        chosen = "hybrid"
    elif structural_sl is not None:
        dynamic_sl = structural_sl
        chosen = "structural"
    elif mechanical_sl is not None:
        dynamic_sl = mechanical_sl
        chosen = "mechanical"
    else:
        return None, "none"
    
    return float(dynamic_sl), chosen


def main():
    print("=" * 70)
    print("END-TO-END: ICT → Confluence → Simulated Activator → Simulated Trailing")
    print("=" * 70)
    
    # 1. Fetch real data
    print("\n1. Fetching BTC/USDT 1d candles...")
    candles = asyncio.run(fetch_candles("BTC", "1d", limit=200))
    print(f"   Fetched {len(candles)} candles, latest close={candles[-1]['close']}")
    
    # 2. ICT Engine
    print("\n2. Running ICT Engine...")
    ict = ict_analyze(candles, pivot_len=5, atr_mult=0.3, atr_len=14, entry_mode="ob_or_fvg")
    print(f"   Signal: {ict.signal}, Bias: {ict.bias}, Grade: {ict.grade}")
    print(f"   Forward levels: {len(ict.forward_levels)}")
    for lvl in ict.forward_levels[:5]:
        print(f"      → {lvl.kind} @ {lvl.price:.2f} ({lvl.distance_pct:.3f}%)")
    print(f"   Support levels: {len(ict.support_levels)}")
    for lvl in ict.support_levels[:5]:
        print(f"      → {lvl.kind} @ {lvl.price:.2f} ({lvl.distance_pct:.3f}%)")
    
    # 3. Confluence Engine
    print("\n3. Running Confluence Engine...")
    confluence = analyze_confluence(candles, "BTC", "1d")
    if confluence is None:
        print("   ❌ Confluence returned None")
        return
    
    print(f"   Direction: {confluence.direction}")
    print(f"   Entry: {confluence.entry_price}")
    print(f"   SL: {confluence.stop_loss}")
    print(f"   TP1: {confluence.take_profit_1} (src: {confluence.features.get('tp1_source')})")
    print(f"   TP2: {confluence.take_profit_2} (src: {confluence.features.get('tp2_source')})")
    print(f"   Forward levels in features: {len(confluence.features.get('forward_levels', []))}")
    print(f"   Support levels in features: {len(confluence.features.get('support_levels', []))}")
    
    # 4. Simulate BotActivator creating position
    print("\n4. Simulating BotActivator → Position.extra_config...")
    extra_config = {
        "forward_levels": confluence.features.get("forward_levels", []),
        "support_levels": confluence.features.get("support_levels", []),
        "tp1_source": confluence.features.get("tp1_source", "unknown"),
        "tp2_source": confluence.features.get("tp2_source", "unknown"),
        "entry_price": confluence.entry_price,
        "stop_loss": confluence.stop_loss,
    }
    print(f"   extra_config keys: {list(extra_config.keys())}")
    print(f"   support_levels count: {len(extra_config['support_levels'])}")
    
    # 5. Simulate TrailingWorker at different price levels
    print("\n5. Simulating TrailingWorker at various price levels...")
    
    entry = float(confluence.entry_price)
    sl = float(confluence.stop_loss)
    side = confluence.direction
    risk_pct = abs(entry - sl) / entry  # approximate
    
    bot_dynamic_sl = {
        "enabled": True,
        "step_r": 0.5,
        "max_steps": 5,
    }
    
    # Test prices: entry, +1%, +3%, +5%, +10%, +15%
    test_prices = [entry, entry * 1.01, entry * 1.03, entry * 1.05, entry * 1.10, entry * 1.15]
    
    print(f"\n   Entry: {entry:.2f} | SL: {sl:.2f} | Side: {side} | Risk%: {risk_pct:.4f}")
    print(f"   {'Price':>12} {'Dynamic SL':>14} {'Source':>12} {'Notes':>30}")
    print(f"   {'-'*12} {'-'*14} {'-'*12} {'-'*30}")
    
    for price in test_prices:
        dyn_sl, source = simulate_trailing_worker(
            extra_config, entry, price, side, risk_pct, bot_dynamic_sl
        )
        notes = ""
        if dyn_sl:
            if side == "long" and dyn_sl > sl:
                notes = f"SL improved by +{((dyn_sl/sl)-1)*100:.2f}%"
            elif side == "short" and dyn_sl < sl:
                notes = f"SL improved by +{((sl/dyn_sl)-1)*100:.2f}%"
            else:
                notes = "No improvement"
        else:
            notes = "No dynamic SL yet"
        
        price_str = f"{price:.2f}"
        sl_str = f"{dyn_sl:.2f}" if dyn_sl else "N/A"
        print(f"   {price_str:>12} {sl_str:>14} {source:>12} {notes:>30}")
    
    # 6. Verify that support_levels are present and usable
    print("\n6. Validation...")
    checks = []
    checks.append(("ICT signal generated", ict.signal != "none"))
    checks.append(("Forward levels present", len(ict.forward_levels) > 0))
    checks.append(("Support levels present", len(ict.support_levels) > 0))
    checks.append(("Confluence TP1 is structural", confluence.features.get("tp1_source") != "fallback_1.5R"))
    checks.append(("Support levels in extra_config", len(extra_config["support_levels"]) > 0))
    
    for name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"   {status} {name}")
    
    all_passed = all(p for _, p in checks)
    print(f"\n{'='*70}")
    if all_passed:
        print("✅ END-TO-END TEST PASSED")
    else:
        print("❌ END-TO-END TEST FAILED")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
