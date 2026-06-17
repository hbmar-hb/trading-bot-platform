import asyncio
import sys
sys.path.insert(0, '/app')
from app.services.database import AsyncSessionLocal
from app.models.exchange_trade import ExchangeTrade
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExchangeTrade).where(ExchangeTrade.raw_data.isnot(None))
        )
        trades = result.scalars().all()
        stats = {'LONG': 0, 'SHORT': 0, 'none': 0}
        for t in trades:
            raw = t.raw_data if t.raw_data else ""
            if "'positionSide': 'LONG'" in raw:
                stats['LONG'] += 1
            elif "'positionSide': 'SHORT'" in raw:
                stats['SHORT'] += 1
            else:
                stats['none'] += 1
        print(f"Stats: {stats}")

asyncio.run(main())
