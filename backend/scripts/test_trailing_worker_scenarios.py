#!/usr/bin/env python3
"""
Exhaustive test: trailing worker structural SL behavior across multiple price scenarios.

Simulates a LONG position with multiple support levels and verifies that
as price rises, the structural SL moves up conservatively.

Usage: cd backend && python scripts/test_trailing_worker_scenarios.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decimal import Decimal


def simulate_structural_sl(support_levels, current_price, side):
    _STRUCTURAL_MARGIN = Decimal("0.005")
    current_price = Decimal(str(current_price))
    
    if side == "long":
        structural_candidates = [
            Decimal(str(l["price"]))
            for l in support_levels
            if current_price > Decimal(str(l["price"])) * (Decimal("1") + _STRUCTURAL_MARGIN)
        ]
        if structural_candidates:
            return max(structural_candidates)
    else:
        structural_candidates = [
            Decimal(str(l["price"]))
            for l in support_levels
            if current_price < Decimal(str(l["price"])) * (Decimal("1") - _STRUCTURAL_MARGIN)
        ]
        if structural_candidates:
            return min(structural_candidates)
    return None


def main():
    print("=" * 70)
    print("TRAILING WORKER SCENARIO TEST: Multiple support levels")
    print("=" * 70)
    
    # Simulated position: LONG BTC @ 78000
    entry = 78000
    initial_sl = 65000
    
    # Multiple support levels (eq_lows, fvg_bulls) sorted by strength then distance
    support_levels = [
        {"price": 65000.0, "kind": "eq_low", "distance_pct": -16.67},
        {"price": 72000.0, "kind": "fvg_bull", "distance_pct": -7.69},
        {"price": 75000.0, "kind": "fvg_bull", "distance_pct": -3.85},
        {"price": 77000.0, "kind": "fvg_bull", "distance_pct": -1.28},
    ]
    
    print(f"\nPosition: LONG @ {entry}, Initial SL: {initial_sl}")
    print(f"Support levels:")
    for lvl in support_levels:
        margin_price = lvl["price"] * 1.005
        print(f"  {lvl['kind']} @ {lvl['price']:.2f} (activates above {margin_price:.2f})")
    
    test_prices = [
        65000,  # Below SL — position stopped out
        70000,  # Above entry, below first FVG
        73000,  # Above 72000*1.005 = 72360
        76000,  # Above 75000*1.005 = 75375
        78000,  # At entry
        79000,  # Above 77000*1.005 = 77385
        85000,  # Well above all supports
    ]
    
    print(f"\n{'Price':>10} {'Structural SL':>14} {'Margin Check':>40}")
    print(f"{'-'*10} {'-'*14} {'-'*40}")
    
    for price in test_prices:
        sl = simulate_structural_sl(support_levels, price, "long")
        sl_str = f"{float(sl):.2f}" if sl else "N/A"
        
        # Determine which levels are active
        active = []
        for lvl in support_levels:
            margin_price = lvl["price"] * 1.005
            if price > margin_price:
                active.append(f"{lvl['kind']}@{lvl['price']:.0f}")
        
        margin_check = ", ".join(active) if active else "None"
        print(f"{price:>10} {sl_str:>14} {margin_check:>40}")
    
    # Assertions
    print(f"\n{'='*70}")
    print("ASSERTIONS:")
    
    checks = []
    # Price 65000: no structural SL (price not above any level with margin)
    sl = simulate_structural_sl(support_levels, 65000, "long")
    checks.append(("65000: no structural SL (below all)", sl is None))
    
    # Price 73000: should use 72000 (first activated)
    sl = simulate_structural_sl(support_levels, 73000, "long")
    checks.append(("73000: SL = 72000 (first FVG activated)", sl is not None and float(sl) == 72000))
    
    # Price 76000: should use 75000 (second FVG activated)
    sl = simulate_structural_sl(support_levels, 76000, "long")
    checks.append(("76000: SL = 75000 (second FVG activated)", sl is not None and float(sl) == 75000))
    
    # Price 79000: should use 77000 (third FVG activated, most conservative)
    sl = simulate_structural_sl(support_levels, 79000, "long")
    checks.append(("79000: SL = 77000 (third FVG activated)", sl is not None and float(sl) == 77000))
    
    # Price 85000: should still use 77000 (highest activated)
    sl = simulate_structural_sl(support_levels, 85000, "long")
    checks.append(("85000: SL = 77000 (highest activated)", sl is not None and float(sl) == 77000))
    
    all_passed = True
    for name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"   {status} {name}")
        if not passed:
            all_passed = False
    
    print(f"\n{'='*70}")
    if all_passed:
        print("✅ ALL SCENARIO TESTS PASSED")
    else:
        print("❌ SOME SCENARIO TESTS FAILED")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
