import asyncio
import os
os.chdir('/app')
import sys
sys.path.insert(0, '/app')

from app.exchanges.factory import create_exchange
from app.services.database import get_db
from sqlalchemy import select
from app.models.exchange_account import ExchangeAccount

async def check():
    async for db in get_db():
        result = await db.execute(select(ExchangeAccount).where(ExchangeAccount.exchange == 'bingx'))
        account = result.scalar_one()
        
        exchange = create_exchange(account)
        try:
            positions = await exchange.get_open_positions()
            print(f"Total posiciones: {len(positions)}")
            for pos in positions:
                print(f"\nSymbol: {pos.symbol}")
                print(f"  Side: {pos.side}")
                print(f"  Entry: {pos.entry_price}")
                print(f"  Qty: {pos.quantity}")
                print(f"  PnL: {pos.unrealized_pnl}")
                print(f"  Position ID: {pos.exchange_position_id}")
                # Verificar si hay más atributos
                print(f"  All attrs: {dir(pos)}")
        finally:
            await exchange.close()
        break

asyncio.run(check())
