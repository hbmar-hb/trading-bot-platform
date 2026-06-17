import asyncio
import sys
sys.path.insert(0, '/app')
from app.services.database import AsyncSessionLocal
from app.models.position import Position
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Position).where(Position.status == 'open', Position.source == 'ai_bot')
        )
        positions = result.scalars().all()
        for p in positions:
            print(f"{p.symbol} | {p.side} | entry={p.entry_price} | qty={p.quantity} | unrealized_pnl={p.unrealized_pnl} | leverage={p.leverage}")

asyncio.run(main())
