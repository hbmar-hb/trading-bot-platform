"""
Test del endpoint de importación
"""
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
from app.utils.crypto import decrypt

csv_sample = """Time,Symbol,Side,Price,Quantity,Realized Profit,Fee,Order ID
2025-12-19 21:53:02,SOL-USDT,Buy,185.85,0.27,-,-,123456789
2025-12-19 22:10:15,SOL-USDT,Sell,186.50,0.27,0.1755,0.0503,123456790
"""

async def test_import():
    from app.api.routes.exchange_trades import import_csv_trades
    from fastapi import HTTPException
    
    async with AsyncSessionLocal() as db:
        # Obtener cuenta
        result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.exchange == "bingx").limit(1)
        )
        account = result.scalar_one_or_none()
        
        if not account:
            print("No hay cuenta bingx")
            return
        
        print(f"Account: {account.label} ({account.id})")
        
        try:
            # Llamar directamente al endpoint
            response = await import_csv_trades(
                account_id=account.id,
                csv_data=csv_sample,
                user_id=account.user_id,
                db=db
            )
            print(f"Respuesta: {response}")
        except HTTPException as e:
            print(f"HTTP Error {e.status_code}: {e.detail}")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_import())
