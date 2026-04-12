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
        
        # Probar fetch_closed_orders directamente
        try:
            orders = await exchange._client.fetch_closed_orders('SOL/USDT:USDT', limit=5)
            print(f"\n=== SOL/USDT Orders ({len(orders)}) ===")
            for o in orders[:3]:
                info = o.get('info', {})
                print(f"\nOrder ID: {o.get('id')}")
                print(f"  Status: {o.get('status')}")
                print(f"  Side: {o.get('side')}")
                print(f"  Filled: {o.get('filled')}")
                print(f"  Average: {o.get('average')}")
                print(f"  Fee: {o.get('fee')}")
                print(f"  Info keys: {sorted(info.keys())}")
                
                # Buscar campos de profit
                for key in sorted(info.keys()):
                    val = info[key]
                    if any(term in key.lower() for term in ['profit', 'pnl', 'realised', 'realized', 'income']):
                        print(f"  -> PROFIT FIELD {key}: {val} (type: {type(val).__name__})")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
