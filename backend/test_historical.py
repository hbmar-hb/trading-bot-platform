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
from datetime import datetime, timezone
import time

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
        
        # Probar con 1 año de historial
        now = time.time()
        since_ts = int((now - 365 * 24 * 3600) * 1000)
        since_dt = datetime.fromtimestamp(since_ts / 1000, tz=timezone.utc)
        
        print(f"\n=== Solicitando trades desde {since_dt.strftime('%Y-%m-%d')} (1 año) ===")
        
        trades = await exchange.get_trade_history(limit=1000, since=since_ts)
        
        print(f"\nTotal trades obtenidos: {len(trades)}")
        
        if trades:
            timestamps = [t['timestamp'] for t in trades if t.get('timestamp')]
            if timestamps:
                min_ts = min(timestamps)
                max_ts = max(timestamps)
                min_dt = datetime.fromtimestamp(min_ts / 1000, tz=timezone.utc)
                max_dt = datetime.fromtimestamp(max_ts / 1000, tz=timezone.utc)
                print(f"Rango de fechas: {min_dt.strftime('%Y-%m-%d')} a {max_dt.strftime('%Y-%m-%d')}")
                
                # Agrupar por mes
                by_month = {}
                for t in trades:
                    ts = t.get('timestamp', 0)
                    if ts:
                        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                        month_key = dt.strftime('%Y-%m')
                        by_month[month_key] = by_month.get(month_key, 0) + 1
                
                print(f"\nTrades por mes:")
                for month, count in sorted(by_month.items()):
                    print(f"  {month}: {count} trades")
        
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
