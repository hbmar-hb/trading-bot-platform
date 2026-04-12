import asyncio
import os
os.chdir('/app')
import sys
sys.path.insert(0, '/app')

from app.services.database import get_db
from sqlalchemy import select
from app.models.exchange_account import ExchangeAccount
from app.models.bot_config import BotConfig
from app.models.position import Position
from app.exchanges.factory import create_exchange
from app.models.paper_balance import PaperBalance
from app.models.user import User

async def test_unified():
    async for db in get_db():
        # Obtener primer usuario
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one()
        user_id = user.id
        print(f'User ID: {user_id}')
        
        # 1. Posiciones de bots
        result_bots = await db.execute(
            select(Position, BotConfig, ExchangeAccount)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .outerjoin(ExchangeAccount, BotConfig.exchange_account_id == ExchangeAccount.id)
            .where(
                BotConfig.user_id == user_id,
                Position.status == 'open',
                BotConfig.exchange_account_id.is_not(None),
            )
        )
        bot_positions = result_bots.all()
        print(f'Bots positions: {len(bot_positions)}')
        for p, bot, acc in bot_positions:
            exch = acc.exchange if acc else "unknown"
            print(f'  - {p.symbol} ({exch})')
        
        # 2. Posiciones paper
        result_paper = await db.execute(
            select(Position, BotConfig, PaperBalance)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .join(PaperBalance, BotConfig.paper_balance_id == PaperBalance.id)
            .where(
                BotConfig.user_id == user_id,
                Position.status == 'open',
                BotConfig.paper_balance_id.is_not(None),
            )
        )
        paper_positions = result_paper.all()
        print(f'Paper positions: {len(paper_positions)}')
        
        # 3. Cuentas de exchange
        accounts_result = await db.execute(
            select(ExchangeAccount)
            .where(ExchangeAccount.user_id == user_id, ExchangeAccount.is_active == True)
        )
        accounts = accounts_result.scalars().all()
        print(f'Exchange accounts: {len(accounts)}')
        
        for account in accounts:
            print(f'  Account: {account.exchange} ({account.id})')
            try:
                exchange = create_exchange(account)
                try:
                    live_positions = await exchange.get_open_positions()
                    print(f'    Live positions: {len(live_positions)}')
                    for pos in live_positions:
                        print(f'      - {pos.symbol} {pos.side}')
                finally:
                    await exchange.close()
            except Exception as e:
                print(f'    ERROR: {e}')
        
        break

asyncio.run(test_unified())
