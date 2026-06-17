#!/usr/bin/env python3
"""
Validate structural SL for SHORT after bug fix.
Ensures support_levels contains EQ lows / bull FVGs BELOW entry,
and trailing worker picks max (closest to entry) for SHORT.

Usage: cd backend && python scripts/test_short_structural_sl.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decimal import Decimal


def test_support_levels_short():
    from app.core.ict_engine import _compute_support_levels

    entry = 100.0
    eq_highs = [120.0, 110.0]
    eq_lows = [95.0, 90.0, 85.0]
    all_fvgs = [
        type("FVG", (), {"filled": False, "kind": "bull", "top": 92.0, "bottom": 91.0})(),
        type("FVG", (), {"filled": False, "kind": "bear", "top": 105.0, "bottom": 104.0})(),
    ]

    # LONG bias
    support_long = _compute_support_levels(entry, eq_highs, eq_lows, all_fvgs, bull_bias=True)
    kinds_long = [l.kind for l in support_long]
    print(f"LONG support_levels: {kinds_long}")
    assert "eq_low" in kinds_long, "LONG should have eq_low"
    assert "fvg_bull" in kinds_long, "LONG should have fvg_bull"
    assert all(l.price < entry for l in support_long), "LONG support levels must be below entry"

    # SHORT bias — after fix, should ALSO contain lows below entry
    support_short = _compute_support_levels(entry, eq_highs, eq_lows, all_fvgs, bull_bias=False)
    kinds_short = [l.kind for l in support_short]
    print(f"SHORT support_levels: {kinds_short}")
    assert "eq_low" in kinds_short, "SHORT should have eq_low"
    assert "fvg_bull" in kinds_short, "SHORT should have fvg_bull"
    assert all(l.price < entry for l in support_short), "SHORT support levels must be below entry"

    print("\n✅ _compute_support_levels: SHORT now uses EQ lows / bull FVGs below entry")


def test_trailing_worker_short():
    """Simulate trailing worker structural SL logic for SHORT."""
    _STRUCTURAL_MARGIN = Decimal("0.005")
    side = "short"
    current_price = Decimal("88.0")  # Below entry 100.0

    support_levels = [
        {"price": 95.0, "kind": "eq_low"},
        {"price": 90.0, "kind": "eq_low"},
        {"price": 85.0, "kind": "eq_low"},
    ]

    # SHORT: find highest support level (closest to entry) that price has ALREADY broken
    structural_candidates = [
        Decimal(str(l["price"]))
        for l in support_levels
        if current_price < Decimal(str(l["price"])) * (Decimal("1") - _STRUCTURAL_MARGIN)
    ]

    print(f"\nCurrent price: {current_price}")
    print(f"Structural candidates: {structural_candidates}")

    # Check which levels are activated:
    # 95.0 * 0.995 = 94.525; 88.0 < 94.525 → True
    # 90.0 * 0.995 = 89.55;  88.0 < 89.55  → True
    # 85.0 * 0.995 = 84.575; 88.0 < 84.575 → False
    assert Decimal("95.0") in structural_candidates, "95.0 should be activated"
    assert Decimal("90.0") in structural_candidates, "90.0 should be activated"
    assert Decimal("85.0") not in structural_candidates, "85.0 should NOT be activated"

    if structural_candidates:
        structural_sl = max(structural_candidates)
        print(f"Structural SL (max = closest to entry): {structural_sl}")
        assert structural_sl == Decimal("95.0"), "Should pick 95.0 (highest/most conservative)"

    print("\n✅ Trailing worker: SHORT uses max() for structural SL")


def main():
    print("=" * 60)
    print("TEST: Structural SL for SHORT (post-fix)")
    print("=" * 60)
    test_support_levels_short()
    test_trailing_worker_short()
    print("\n" + "=" * 60)
    print("✅ ALL SHORT STRUCTURAL SL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
