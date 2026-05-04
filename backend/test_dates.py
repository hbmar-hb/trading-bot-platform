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
        
        # Probar diferentes rangos de fechas
        now = time.time()
        ranges = [
            ("7 dias", int((now - 7 * 24 * 3600) * 1000)),
            ("30 dias", int((now - 30 * 24 * 3600) * 1000)),
            ("90 dias", int((now - 90 * 24 * 3600) * 1000)),
        ]
        
        for label, since_ts in ranges:
            since_dt = datetime.fromtimestamp(since_ts / 1000, tz=timezone.utc)
            print(f"\n=== {label} (desde {since_dt.strftime('%Y-%m-%d')}) ===")
            
            trades = await exchange.get_trade_history(limit=500, since=since_ts)
            print(f"Trades obtenidos: {len(trades)}")
            
            if trades:
                # Mostrar rango de fechas de los trades
                timestamps = [t['timestamp'] for t in trades if t.get('timestamp')]
                if timestamps:
                    min_ts = min(timestamps)
                    max_ts = max(timestamps)
                    min_dt = datetime.fromtimestamp(min_ts / 1000, tz=timezone.utc)
                    max_dt = datetime.fromtimestamp(max_ts / 1000, tz=timezone.utc)
                    print(f"Rango: {min_dt.strftime('%Y-%m-%d')} a {max_dt.strftime('%Y-%m-%d')}")
        
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
