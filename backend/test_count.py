import asyncio
import sys
sys.path.insert(0, '/app')
from app.services.database import AsyncSessionLocal
from app.models.exchange_trade import ExchangeTrade
from sqlalchemy import select, func

async def main():
    async with AsyncSessionLocal() as db:
        total = await db.scalar(select(func.count()).select_from(ExchangeTrade))
        with_raw = await db.scalar(select(func.count()).select_from(ExchangeTrade).where(ExchangeTrade.raw_data.isnot(None)))
        ai_bot = await db.scalar(select(func.count()).select_from(ExchangeTrade).where(ExchangeTrade.source == 'ai_bot'))
        print(f"Total trades: {total}")
        print(f"Con raw_data: {with_raw}")
        print(f"AI bot trades: {ai_bot}")
        
        # Verificar sources
        result = await db.execute(select(ExchangeTrade.source, func.count()).group_by(ExchangeTrade.source))
        for row in result.all():
            print(f"  {row[0]}: {row[1]}")

asyncio.run(main())
