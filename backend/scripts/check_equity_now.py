import sys
sys.path.insert(0, "/app")
import asyncio
from app.exchanges.factory import create_exchange
from app.services.database import SessionLocal
from sqlalchemy import text

async def check():
    with SessionLocal() as db:
        # Get one AI bot with exchange account
        r = db.execute(text("""
            SELECT bc.id, bc.bot_name, bc.symbol, ea.id as eaid, ea.exchange
            FROM bot_configs bc
            JOIN exchange_accounts ea ON bc.exchange_account_id = ea.id
            WHERE bc.status = 'active' AND bc.ai_signal_mode = true
            LIMIT 1
        """))
        bot = r.fetchone()
        if not bot:
            print("No AI bots with exchange account found")
            return
        
        print(f"Checking account for bot: {bot.bot_name}")
        
        from app.models.exchange_account import ExchangeAccount
        ea = db.get(ExchangeAccount, bot.eaid)
        exchange = create_exchange(ea)
        
        eq = await exchange.get_equity()
        print(f"get_equity total_equity: {eq.total_equity}")
        
        # Check recent closed positions
        r2 = db.execute(text("""
            SELECT symbol, side, realized_pnl, closed_at
            FROM positions
            WHERE status = 'closed' AND closed_at > NOW() - INTERVAL '6 hours'
            ORDER BY closed_at DESC
        """))
        print("\nClosed positions last 6h:")
        total_pnl = 0.0
        for row in r2.fetchall():
            pnl = float(row.realized_pnl or 0)
            total_pnl += pnl
            print(f"  {row.closed_at.strftime('%H:%M')} {row.symbol:16s} {row.side:5s} P&L={pnl:+.4f}")
        print(f"  Total realized P&L: {total_pnl:+.4f}")
        
        await exchange.close()

asyncio.run(check())
