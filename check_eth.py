import asyncio
import os
os.chdir('/app')
import sys
sys.path.insert(0, '/app')

from sqlalchemy import select
from app.services.database import get_db
from app.models.position import Position
from app.models.bot_config import BotConfig
from app.models.exchange_account import ExchangeAccount

async def check():
    async for db in get_db():
        print("=== POSICIONES ABIERTAS ===")
        result = await db.execute(
            select(Position, BotConfig, ExchangeAccount)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .outerjoin(ExchangeAccount, BotConfig.exchange_account_id == ExchangeAccount.id)
            .where(Position.status == "open")
        )
        for pos, bot, acc in result.all():
            exch = acc.exchange if acc else "paper"
            print(f"Position: {pos.symbol} {pos.side}")
            print(f"  Bot: {bot.bot_name} (ID: {bot.id})")
            print(f"  Exchange: {exch}")
            print(f"  Status: {bot.status}")
            print(f"  exchange_order_id: {pos.exchange_order_id}")
            print()
        
        print("\n=== TODOS LOS BOTS ===")
        result = await db.execute(select(BotConfig))
        for bot in result.scalars().all():
            print(f"Bot: {bot.bot_name}")
            print(f"  ID: {bot.id}")
            print(f"  Symbol: {bot.symbol}")
            print(f"  Status: {bot.status}")
            print(f"  exchange_account_id: {bot.exchange_account_id}")
            print(f"  paper_balance_id: {bot.paper_balance_id}")
            print()
        
        break

asyncio.run(check())
