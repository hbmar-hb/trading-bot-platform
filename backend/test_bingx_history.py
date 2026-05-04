"""
Script de diagnóstico para verificar límites de historial de BingX API
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

async def test_endpoints():
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
        
        # Fechas de referencia
        now = time.time() * 1000
        one_year_ago = int((time.time() - 365 * 24 * 3600) * 1000)
        six_months_ago = int((time.time() - 180 * 24 * 3600) * 1000)
        three_months_ago = int((time.time() - 90 * 24 * 3600) * 1000)
        
        print(f"\n=== Fechas de referencia ===")
        print(f"Hoy: {datetime.fromtimestamp(now/1000, tz=timezone.utc).strftime('%Y-%m-%d')}")
        print(f"1 año atrás: {datetime.fromtimestamp(one_year_ago/1000, tz=timezone.utc).strftime('%Y-%m-%d')}")
        print(f"6 meses atrás: {datetime.fromtimestamp(six_months_ago/1000, tz=timezone.utc).strftime('%Y-%m-%d')}")
        print(f"3 meses atrás: {datetime.fromtimestamp(three_months_ago/1000, tz=timezone.utc).strftime('%Y-%m-%d')}")
        
        test_symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']
        
        # Test 1: fetch_closed_orders con paginación
        print(f"\n=== TEST 1: fetch_closed_orders (órdenes cerradas) ===")
        for sym in test_symbols[:1]:  # Probar con BTC
            try:
                print(f"\nSímbolo: {sym}")
                
                # Intentar obtener historial de 1 año
                all_orders = []
                since = one_year_ago
                limit = 100
                
                for page in range(10):  # Hasta 1000 órdenes
                    params = {'limit': limit}
                    if page > 0 and all_orders:
                        params['fromId'] = all_orders[-1]['id']
                    
                    orders = await exchange.fetch_closed_orders(sym, since=since, limit=limit, params=params)
                    
                    if not orders:
                        break
                    
                    all_orders.extend(orders)
                    
                    if len(orders) < limit:
                        break
                
                print(f"  Total órdenes obtenidas: {len(all_orders)}")
                
                if all_orders:
                    timestamps = [o['timestamp'] for o in all_orders if o.get('timestamp')]
                    if timestamps:
                        oldest = datetime.fromtimestamp(min(timestamps)/1000, tz=timezone.utc)
                        newest = datetime.fromtimestamp(max(timestamps)/1000, tz=timezone.utc)
                        print(f"  Más antigua: {oldest.strftime('%Y-%m-%d %H:%M')}")
                        print(f"  Más reciente: {newest.strftime('%Y-%m-%d %H:%M')}")
                        
                        # Mostrar distribución por mes
                        by_month = {}
                        for ts in timestamps:
                            dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc)
                            month = dt.strftime('%Y-%m')
                            by_month[month] = by_month.get(month, 0) + 1
                        
                        print(f"  Distribución por mes:")
                        for month, count in sorted(by_month.items()):
                            print(f"    {month}: {count}")
                        
            except Exception as e:
                print(f"  Error: {e}")
        
        # Test 2: fetch_my_trades (fills/executions)
        print(f"\n=== TEST 2: fetch_my_trades (fills/executions) ===")
        for sym in test_symbols[:1]:
            try:
                print(f"\nSímbolo: {sym}")
                
                trades = await exchange.fetch_my_trades(sym, since=one_year_ago, limit=100)
                print(f"  Total trades obtenidos: {len(trades)}")
                
                if trades:
                    timestamps = [t['timestamp'] for t in trades if t.get('timestamp')]
                    if timestamps:
                        oldest = datetime.fromtimestamp(min(timestamps)/1000, tz=timezone.utc)
                        newest = datetime.fromtimestamp(max(timestamps)/1000, tz=timezone.utc)
                        print(f"  Más antigua: {oldest.strftime('%Y-%m-%d %H:%M')}")
                        print(f"  Más reciente: {newest.strftime('%Y-%m-%d %H:%M')}")
                        
            except Exception as e:
                print(f"  Error: {e}")
        
        # Test 3: Verificar si hay endpoint de income/profit history
        print(f"\n=== TEST 3: Información de la cuenta ===")
        try:
            balance = await exchange.fetch_balance({'type': 'swap'})
            print(f"Balance USDT: {balance.get('USDT', {}).get('total', 'N/A')}")
        except Exception as e:
            print(f"Error balance: {e}")
        
        await exchange.close()
        
        print(f"\n=== DIAGNÓSTICO COMPLETADO ===")
        print(f"Si las fechas más antiguas son de abril 2026, BingX tiene limitación de retención.")
        print(f"Si ves fechas de 2025, el problema está en cómo filtramos los datos.")

if __name__ == "__main__":
    asyncio.run(test_endpoints())
