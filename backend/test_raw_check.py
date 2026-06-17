import asyncio
import sys
sys.path.insert(0, '/app')
from app.services.database import AsyncSessionLocal
from app.models.exchange_trade import ExchangeTrade
from sqlalchemy import select, desc
import ast

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExchangeTrade).where(ExchangeTrade.source == 'ai_bot').order_by(desc(ExchangeTrade.closed_at))
        )
        trades = result.scalars().all()
        for t in trades:
            raw = t.raw_data if t.raw_data else ""
            try:
                d = ast.literal_eval(raw)
                pos_side = d.get('positionSide', 'N/A')
                order_side = d.get('side', 'N/A')
            except Exception as e:
                pos_side = f'err:{e}'
                order_side = 'err'
            print(f"{t.symbol} | DB_side={t.side} | order_side={order_side} | positionSide={pos_side} | entry={t.entry_price} | exit={t.exit_price} | pnl={t.realized_pnl}")

asyncio.run(main())
