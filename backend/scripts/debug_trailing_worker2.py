#!/usr/bin/env python3
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
    print("DEBUG: TrailingWorker evaluation at price 95000")
    print("=" * 70)
    
    position_id = "261114c6-c048-446e-9ea4-23eab8f69e6f"
    current_price = Decimal("95000")
    
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
        print(f"Entry: {position.entry_price}")
        print(f"Current SL: {position.current_sl_price}")
        print(f"Side: {position.side}")
        print(f"Extra config keys: {list((position.extra_config or {}).keys())}")
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
        
        # Refresh position from DB
        await db.refresh(position)
        print(f"\nAfter evaluation:")
        print(f"  Current SL: {position.current_sl_price}")
        print(f"  dynamic_sl_source: {(position.extra_config or {}).get('dynamic_sl_source')}")
        print(f"  dynamic_sl_steps: {(position.extra_config or {}).get('dynamic_sl_steps')}")


if __name__ == "__main__":
    asyncio.run(main())
