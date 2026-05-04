"""
Probar fetchPositionsHistory que aparece como método disponible
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
        
        import ccxt.async_support as ccxt
        exchange = ccxt.bingx({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        
        one_year_ago = int((time.time() - 365 * 24 * 3600) * 1000)
        
        print(f"\n=== Probando fetchPositionsHistory ===")
        print(f"Desde: {datetime.fromtimestamp(one_year_ago/1000, tz=timezone.utc).strftime('%Y-%m-%d')}")
        
        try:
            # Intentar obtener historial de posiciones
            positions = await exchange.fetch_positions_history(since=one_year_ago, limit=1000)
            
            print(f"\nPosiciones encontradas: {len(positions)}")
            
            if positions:
                # Analizar fechas
                timestamps = []
                for p in positions:
                    # Buscar timestamp en varios campos posibles
                    ts = p.get('timestamp') or p.get('closeTime') or p.get('updateTime')
                    if ts:
                        timestamps.append(ts)
                
                if timestamps:
                    oldest = datetime.fromtimestamp(min(timestamps)/1000, tz=timezone.utc)
                    newest = datetime.fromtimestamp(max(timestamps)/1000, tz=timezone.utc)
                    
                    print(f"Más antigua: {oldest.strftime('%Y-%m-%d')}")
                    print(f"Más reciente: {newest.strftime('%Y-%m-%d')}")
                    
                    # Mostrar primera posición como ejemplo
                    print(f"\nEjemplo de posición:")
                    p = positions[0]
                    print(f"  Info: {p.get('info', {})}")
                    
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        
        # También probar fetchLedger
        print(f"\n=== Probando fetchLedger ===")
        try:
            ledger = await exchange.fetch_ledger(since=one_year_ago, limit=1000)
            
            print(f"\nEntradas en ledger: {len(ledger)}")
            
            if ledger:
                timestamps = [e.get('timestamp') for e in ledger if e.get('timestamp')]
                if timestamps:
                    oldest = datetime.fromtimestamp(min(timestamps)/1000, tz=timezone.utc)
                    newest = datetime.fromtimestamp(max(timestamps)/1000, tz=timezone.utc)
                    
                    print(f"Más antigua: {oldest.strftime('%Y-%m-%d')}")
                    print(f"Más reciente: {newest.strftime('%Y-%m-%d')}")
                    
                    # Mostrar distribución por tipo
                    by_type = {}
                    for e in ledger:
                        t = e.get('type', 'unknown')
                        by_type[t] = by_type.get(t, 0) + 1
                    
                    print(f"\nPor tipo:")
                    for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
                        print(f"  {t}: {count}")
                    
        except Exception as e:
            print(f"Error: {e}")
        
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
