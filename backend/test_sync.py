import asyncio
import os
import sys
sys.path.insert(0, '/app')
os.environ.setdefault("DATABASE_URL", "postgresql://admin:admin@postgres:5432/tradingbot")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-development")
os.environ.setdefault("ENCRYPTION_KEY", "J9aes0-rB1LOZVXVo28E_lrZuESylLe4eFlhbYbdS5k=")

from sqlalchemy import select
from app.services.database import AsyncSessionLocal
from app.models.exchange_account import ExchangeAccount
from app.exchanges.bingx import BingXExchange
from app.utils.crypto import decrypt

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.exchange == "bingx").limit(1)
        )
        account = result.scalar_one_or_none()
        
        if not account:
            print("No hay cuenta bingx")
            return
            
        print(f"Account: {account.exchange} - {account.label}")
        
        api_key = decrypt(account.api_key_encrypted)
        api_secret = decrypt(account.secret_encrypted)
        
        exchange = BingXExchange(
            api_key=api_key,
            secret=api_secret,
            testnet=False,
        )
        
        # Probar get_trade_history con 30 dias
        import time
        since_ts = int((time.time() - 30 * 24 * 3600) * 1000)
        
        print("\nSolicitando trades de los ultimos 30 dias...")
        trades = await exchange.get_trade_history(limit=500, since=since_ts)
        
        print(f"\n=== Total trades obtenidos: {len(trades)} ===")
        
        # Separar por con y sin PnL
        with_pnl = [t for t in trades if t.get('pnl') is not None]
        without_pnl = [t for t in trades if t.get('pnl') is None]
        
        print(f"  - Con PnL (posiciones cerradas): {len(with_pnl)}")
        print(f"  - Sin PnL (fills/parciales): {len(without_pnl)}")
        
        # Agrupar por simbolo
        by_symbol = {}
        for t in trades:
            sym = t['symbol']
            by_symbol[sym] = by_symbol.get(sym, 0) + 1
        
        print(f"\nTrades por simbolo (top 15):")
        for sym, count in sorted(by_symbol.items(), key=lambda x: -x[1])[:15]:
            print(f"  {sym}: {count}")
        
        # Mostrar trades con PnL
        if with_pnl:
            print(f"\n=== Trades con PnL ({len(with_pnl)} total) ===")
            for t in with_pnl[:15]:
                print(f"{t['symbol']} | {t['side']} | Qty: {float(t['quantity']):.4f} | PnL: {t['pnl']} USDT")
        
        # Mostrar trades sin PnL (muestra)
        if without_pnl:
            print(f"\n=== Trades sin PnL (muestra de 10 de {len(without_pnl)}) ===")
            for t in without_pnl[:10]:
                print(f"{t['symbol']} | {t['side']} | Qty: {float(t['quantity']):.4f} | Price: {float(t['price']):.2f}")
        
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
