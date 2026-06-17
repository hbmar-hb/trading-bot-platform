#!/usr/bin/env python3
"""
Test script: force a paper signal for BTC/USDT 1d and verify:
1. forward_levels + support_levels are computed
2. position.extra_config has the correct fields
3. trailing_worker can read support_levels without errors

Usage: cd backend && python scripts/test_structural_sl_flow.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import json
from datetime import datetime, timezone

from app.services.database import SessionLocal
from app.models.bot_config import BotConfig
from app.models.position import Position
from app.services.ai_scanner import build_signal
from app.tasks.bot_activator_task import activate_signal
from app.engines.bot_activator import _adjust_risk_configs_by_structure, _default_ia_trailing, _default_ia_breakeven


def test_scanner():
    """Run scanner for BTC/USDT 1d and inspect forward/support levels."""
    db = SessionLocal()
    try:
        print("=" * 60)
        print("TEST 1: Scanner signal generation")
        print("=" * 60)

        result, sig = build_signal(db, "BTCUSDT", "1d")

        if sig is None:
            print("❌ No signal generated")
            return None

        feats = sig.features or {}
        forward = feats.get("forward_levels", [])
        support = feats.get("support_levels", [])

        print(f"Direction: {sig.direction}")
        print(f"Score: {sig.score}")
        print(f"Entry: {sig.entry_price}")
        print(f"SL: {sig.stop_loss}")
        print(f"TP1: {sig.take_profit_1} (source: {feats.get('tp1_source')})")
        print(f"TP2: {sig.take_profit_2} (source: {feats.get('tp2_source')})")
        print(f"TP1 close %: {feats.get('tp1_close_pct')}")
        print(f"Forward levels ({len(forward)}):")
        for lvl in forward[:5]:
            print(f"  - {lvl['kind']} @ {lvl['price']} ({lvl['distance_pct']}%)")
        print(f"Support levels ({len(support)}):")
        for lvl in support[:5]:
            print(f"  - {lvl['kind']} @ {lvl['price']} ({lvl['distance_pct']}%)")
        print(f"ML features: tp1_distance_r={feats.get('tp1_distance_r')}, "
              f"tp1_strength={feats.get('tp1_strength')}, "
              f"forward_density={feats.get('forward_density')}")

        if not forward:
            print("⚠️  WARNING: No forward levels — TP will use fallback")
        if not support:
            print("⚠️  WARNING: No support levels — dynamic SL will use mechanical only")

        return sig
    finally:
        db.close()


def test_activator(sig):
    """Activate signal for BTCbot_1d_paper and inspect position."""
    db = SessionLocal()
    try:
        print("\n" + "=" * 60)
        print("TEST 2: Bot activator → position creation")
        print("=" * 60)

        bot = db.query(BotConfig).filter(
            BotConfig.bot_name == "BTCbot_1d_paper"
        ).first()

        if not bot:
            print("❌ BTCbot_1d_paper not found")
            return None

        print(f"Bot: {bot.bot_name} | Paper: {bot.paper_balance_id is not None}")

        # Trigger activation
        result = activate_signal(str(sig.id))
        print(f"Activator result: {result}")

        # Find the position
        position = db.query(Position).filter(
            Position.bot_id == bot.id,
            Position.status == "open"
        ).order_by(Position.opened_at.desc()).first()

        if not position:
            print("❌ No open position found")
            return None

        extra = dict(position.extra_config or {})
        print(f"Position ID: {position.id}")
        print(f"Symbol: {position.symbol}")
        print(f"Side: {position.side}")
        print(f"Entry: {position.entry_price}")
        print(f"SL: {position.current_sl_price}")

        # Verify forward/support levels in extra_config
        fwd = extra.get("forward_levels", [])
        sup = extra.get("support_levels", [])
        adj_tr = extra.get("adjusted_trailing_config", {})
        adj_be = extra.get("adjusted_breakeven_config", {})

        print(f"forward_levels in extra_config: {len(fwd)} items")
        print(f"support_levels in extra_config: {len(sup)} items")
        print(f"adjusted_trailing_config: {json.dumps(adj_tr, indent=2)}")
        print(f"adjusted_breakeven_config: {json.dumps(adj_be, indent=2)}")

        if not fwd:
            print("❌ forward_levels MISSING in position.extra_config")
        if not sup:
            print("❌ support_levels MISSING in position.extra_config")
        if not adj_tr:
            print("❌ adjusted_trailing_config MISSING")
        if not adj_be:
            print("❌ adjusted_breakeven_config MISSING")

        if fwd and sup and adj_tr and adj_be:
            print("✅ All structural fields present in position.extra_config")

        return position
    finally:
        db.close()


def test_trailing_worker_logic(position):
    """Simulate trailing_worker reading support_levels."""
    print("\n" + "=" * 60)
    print("TEST 3: Trailing worker logic simulation")
    print("=" * 60)

    extra = dict(position.extra_config or {})
    support_levels = extra.get("support_levels", [])
    side = position.side

    if not support_levels:
        print("⚠️  No support_levels to test")
        return

    # Simulate various current prices
    entry = float(position.entry_price)
    test_prices = [entry * 1.01, entry * 1.03, entry * 1.05, entry * 1.10]

    _STRUCTURAL_MARGIN = 0.005

    for price in test_prices:
        if side == "long":
            candidates = [
                lvl["price"] for lvl in support_levels
                if price > lvl["price"] * (1 + _STRUCTURAL_MARGIN)
            ]
            structural_sl = max(candidates) if candidates else None
        else:
            candidates = [
                lvl["price"] for lvl in support_levels
                if price < lvl["price"] * (1 - _STRUCTURAL_MARGIN)
            ]
            structural_sl = min(candidates) if candidates else None

        status = "✅ SL would move" if structural_sl else "⏸️  No SL change"
        print(f"Price {price:.2f}: structural_sl={structural_sl} {status}")


def main():
    print("Structural SL Flow Test — BTC/USDT 1d Paper")
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")

    sig = test_scanner()
    if sig is None:
        print("\n❌ Scanner test failed — aborting")
        sys.exit(1)

    position = test_activator(sig)
    if position is None:
        print("\n❌ Activator test failed — aborting")
        sys.exit(1)

    test_trailing_worker_logic(position)

    print("\n" + "=" * 60)
    print("All tests completed")
    print("=" * 60)


if __name__ == "__main__":
    main()
