#!/usr/bin/env python3
"""
Fix the paper position by deleting the malformed one and creating a correct one.

Usage: cd backend && python scripts/fix_paper_position.py
"""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://admin:Capnegret240323@localhost:5433/tradingbot")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://admin:Capnegret240323@localhost:5433/tradingbot")

from datetime import datetime, timezone
from decimal import Decimal
import uuid

from app.services.database import SessionLocal
from app.models.position import Position
from app.models.bot_config import BotConfig
from app.models.paper_balance import PaperBalance


def main():
    print("=" * 70)
    print("FIX PAPER POSITION")
    print("=" * 70)
    
    old_position_id = "c9985392-35df-452d-a63f-5e86ec0714f1"
    bot_id = "7927bd13-d350-4bd9-9892-210a0e8ff49a"  # BTCbot_1d_paper
    
    with SessionLocal() as db:
        # Delete old position
        old = db.query(Position).filter(Position.id == uuid.UUID(old_position_id)).first()
        if old:
            db.delete(old)
            db.commit()
            print(f"✅ Deleted old position {old_position_id}")
        
        bot = db.query(BotConfig).filter(BotConfig.id == uuid.UUID(bot_id)).first()
        if not bot:
            print("❌ Bot not found")
            return
        
        entry_price = 77974.6
        sl_price = 64997.25
        tp1_price = 94654.3
        tp2_price = 101142.975
        quantity = 0.001
        tp1_pct = 0.50
        
        extra_config = {
            "source": "ai_signal",
            "ai_signal_id": str(uuid.uuid4()),
            "score": 80.0,
            "tp1_source": "eq_high",
            "tp2_source": "fvg_bear",
            "forward_levels": [
                {"price": 94654.3, "kind": "eq_high", "distance_pct": 21.391},
                {"price": 78566.7, "kind": "fvg_bear", "distance_pct": 0.759},
                {"price": 84694.3, "kind": "fvg_bear", "distance_pct": 8.618},
            ],
            "support_levels": [
                {"price": 64997.25, "kind": "eq_low", "distance_pct": -16.643},
            ],
            "adjusted_trailing_config": {
                "enabled": True,
                "activation_r": 1.2,
                "step_r": 0.5,
            },
            "adjusted_breakeven_config": {
                "enabled": True,
                "activation_r": 1.0,
            },
            "dynamic_sl_steps": 0,
            "dynamic_sl_source": "initial",
        }
        
        pos = Position(
            id=uuid.uuid4(),
            bot_id=uuid.UUID(bot_id),
            exchange="bingx_paper",
            symbol=bot.symbol,
            side="long",
            entry_price=Decimal(str(entry_price)),
            quantity=Decimal(str(quantity)),
            leverage=bot.leverage or 10,
            current_sl_price=Decimal(str(sl_price)),
            current_tp_prices=[
                {"level": 1, "price": float(tp1_price), "close_percent": int(tp1_pct * 100), "hit": False, "order_id": None},
                {"level": 2, "price": float(tp2_price), "close_percent": int((1 - tp1_pct) * 100), "hit": False, "order_id": None},
            ],
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            exchange_order_id="paper_" + str(uuid.uuid4())[:8],
            exchange_sl_order_id="paper_sl_" + str(uuid.uuid4())[:8],
            status="open",
            opened_at=datetime.now(timezone.utc),
            extra_config=extra_config,
            exchange_position_id="paper_pos_" + str(uuid.uuid4())[:8],
            source="ai_bot",
        )
        
        db.add(pos)
        db.commit()
        db.refresh(pos)
        
        print(f"\n✅ New position created!")
        print(f"   ID: {pos.id}")
        print(f"   Symbol: {pos.symbol}")
        print(f"   Side: {pos.side}")
        print(f"   Entry: {pos.entry_price}")
        print(f"   SL: {pos.current_sl_price}")
        print(f"   TP prices: {pos.current_tp_prices}")
        print(f"   Status: {pos.status}")
        print(f"\n   extra_config:")
        print(f"   - support_levels: {len(extra_config['support_levels'])} items")
        print(f"   - forward_levels: {len(extra_config['forward_levels'])} items")
        print(f"   - tp1_source: {extra_config['tp1_source']}")
    
    print(f"\n{'='*70}")
    print("✅ POSITION FIXED")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
