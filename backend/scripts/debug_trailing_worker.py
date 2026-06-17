#!/usr/bin/env python3
"""
Debug script: evaluate the trailing worker logic for a specific position
with full traceback.

Usage: cd backend && python scripts/debug_trailing_worker.py
"""
import sys, os, asyncio, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://admin:Capnegret240323@localhost:5433/tradingbot")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://admin:Capnegret240323@localhost:5433/tradingbot")

from decimal import Decimal
from sqlalchemy import select
from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
from app.models.position import Position
from app.models.bot_config import BotConfig
from app.workers.trailing_worker import TrailingWorker


async def main():
    print("=" * 70)
    print("DEBUG: TrailingWorker evaluation")
    print("=" * 70)
    
    position_id = "c9985392-35df-452d-a63f-5e86ec0714f1"
    current_price = Decimal("80000")
    
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(Position.id == position_id)
        )
        result = await db.execute(stmt)
        row = result.first()
        
        if not row:
            print(f"❌ Position {position_id} not found")
            return
        
        position, bot = row
        print(f"Position: {position.id}")
        print(f"Symbol: {position.symbol}")
        print(f"Side: {position.side}")
        print(f"Extra config: {position.extra_config}")
        print(f"Bot trailing_config: {bot.trailing_config}")
        print(f"Bot breakeven_config: {bot.breakeven_config}")
        print(f"Bot dynamic_sl_config: {bot.dynamic_sl_config}")
        
        worker = TrailingWorker()
        try:
            await worker._evaluate_position(position, bot, current_price)
            print("\n✅ Evaluation succeeded!")
        except Exception as exc:
            print(f"\n❌ Evaluation failed: {exc}")
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
