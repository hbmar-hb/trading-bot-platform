#!/usr/bin/env python3
"""
One-off migration: update all AI bots' risk configs (trailing, breakeven, dynamic_sl)
to the new timeframe-aware defaults.

Run: python backend/scripts/migrate_risk_configs_by_timeframe.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.database import SessionLocal
from app.models.bot_config import BotConfig


def _default_ia_trailing(timeframe: str = "15m") -> dict:
    tf = (timeframe or "15m").lower()
    if tf in ("1d",):
        return {"enabled": True, "activation_r": 0.8, "callback_rate": 0.8}
    elif tf in ("4h",):
        return {"enabled": True, "activation_r": 1.0, "callback_rate": 0.9}
    elif tf in ("1h",):
        return {"enabled": True, "activation_r": 1.2, "callback_rate": 1.0}
    else:
        return {"enabled": True, "activation_r": 1.5, "callback_rate": 1.0}


def _default_ia_breakeven(timeframe: str = "15m") -> dict:
    tf = (timeframe or "15m").lower()
    if tf in ("1d", "4h"):
        return {"enabled": True, "activation_r": 0.5, "lock_profit": 0.3}
    elif tf in ("1h",):
        return {"enabled": True, "activation_r": 0.8, "lock_profit": 0.25}
    else:
        return {"enabled": True, "activation_r": 1.0, "lock_profit": 0.2}


def _default_ia_dynamic_sl(timeframe: str = "15m") -> dict:
    tf = (timeframe or "15m").lower()
    if tf in ("1d",):
        return {"enabled": True, "step_r": 0.5, "max_steps": 10}
    elif tf in ("4h",):
        return {"enabled": True, "step_r": 0.5, "max_steps": 8}
    elif tf in ("1h",):
        return {"enabled": True, "step_r": 0.5, "max_steps": 7}
    else:
        return {"enabled": True, "step_r": 0.5, "max_steps": 6}


def main():
    db = SessionLocal()
    try:
        bots = db.query(BotConfig).filter(BotConfig.ai_signal_mode == True).all()
        updated = 0
        for bot in bots:
            tf = bot.timeframe or "15m"
            changes = []

            new_trailing = _default_ia_trailing(tf)
            new_breakeven = _default_ia_breakeven(tf)
            new_dynamic_sl = _default_ia_dynamic_sl(tf)

            if bot.trailing_config != new_trailing:
                bot.trailing_config = new_trailing
                changes.append(f"trailing ({tf})")
            if bot.breakeven_config != new_breakeven:
                bot.breakeven_config = new_breakeven
                changes.append(f"breakeven ({tf})")
            if bot.dynamic_sl_config != new_dynamic_sl:
                bot.dynamic_sl_config = new_dynamic_sl
                changes.append(f"dynamic_sl ({tf})")

            if changes:
                updated += 1
                print(f"[MIGRATE] {bot.bot_name}: updated {', '.join(changes)}")

        if updated:
            db.commit()
            print(f"\n[MIGRATE] Committed {updated} bots updated.")
        else:
            print("\n[MIGRATE] No bots needed updating.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
