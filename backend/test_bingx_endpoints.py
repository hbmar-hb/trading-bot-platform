"""
Probar todos los endpoints disponibles de BingX para obtener historial completo
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

async def test_all_endpoints():
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
        
        # Fecha de inicio (1 año atrás)
        one_year_ago = int((time.time() - 365 * 24 * 3600) * 1000)
        
        print(f"\n=== Buscando historial desde {datetime.fromtimestamp(one_year_ago/1000, tz=timezone.utc).strftime('%Y-%m-%d')} ===\n")
        
        all_trades_found = []
        
        # Test 1: fetch_closed_orders con paginación agresiva
        print("1. Probando fetch_closed_orders con paginación...")
        try:
            # Obtener todos los símbolos primero
            markets = await exchange.load_markets()
            swap_symbols = [m['symbol'] for m in markets.values() if m.get('swap') and 'USDT' in m['symbol']]
            
            print(f"   Total símbolos: {len(swap_symbols)}")
            
            for sym in swap_symbols[:100]:  # Probar top 100
                try:
                    # Paginación: obtener hasta 500 órdenes por símbolo
                    all_orders = []
                    last_id = None
                    
                    for page in range(10):  # Max 1000 órdenes
                        params = {'limit': 100}
                        if last_id:
                            params['fromId'] = last_id
                        
                        orders = await exchange.fetch_closed_orders(sym, since=one_year_ago, limit=100, params=params)
                        
                        if not orders:
                            break
                            
                        all_orders.extend(orders)
                        
                        if len(orders) < 100:
                            break
                            
                        last_id = orders[-1]['id']
                    
                    # Filtrar solo las que tienen profit (posiciones cerradas)
                    for o in all_orders:
                        info = o.get('info', {})
                        profit = info.get('profit')
                        if profit and float(profit) != 0:
                            all_trades_found.append({
                                'symbol': sym,
                                'timestamp': o.get('timestamp'),
                                'profit': profit,
                                'side': o.get('side'),
                                'id': o.get('id')
                            })
                            
                except Exception as e:
                    pass
            
            print(f"   Trades con PnL encontrados: {len(all_trades_found)}")
            
        except Exception as e:
            print(f"   Error: {e}")
        
        # Test 2: Intentar con income/funding history si existe
        print("\n2. Probando endpoints alternativos...")
        
        # Verificar métodos disponibles
        methods = [m for m in dir(exchange) if not m.startswith('_') and 'fetch' in m.lower()]
        print(f"   Métodos disponibles con 'fetch': {[m for m in methods if 'income' in m.lower() or 'history' in m.lower() or 'ledger' in m.lower()]}")
        
        # Test 3: fetchMyTrades para cada símbolo
        print("\n3. Probando fetchMyTrades...")
        my_trades_total = []
        try:
            for sym in ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT']:
                try:
                    trades = await exchange.fetch_my_trades(sym, since=one_year_ago, limit=1000)
                    if trades:
                        my_trades_total.extend(trades)
                        print(f"   {sym}: {len(trades)} trades")
                except:
                    pass
            
            print(f"   Total fetchMyTrades: {len(my_trades_total)}")
            
            if my_trades_total:
                timestamps = [t['timestamp'] for t in my_trades_total if t.get('timestamp')]
                if timestamps:
                    oldest = datetime.fromtimestamp(min(timestamps)/1000, tz=timezone.utc)
                    newest = datetime.fromtimestamp(max(timestamps)/1000, tz=timezone.utc)
                    print(f"   Rango: {oldest.strftime('%Y-%m-%d')} a {newest.strftime('%Y-%m-%d')}")
                    
        except Exception as e:
            print(f"   Error: {e}")
        
        await exchange.close()
        
        # Análisis final
        print(f"\n=== RESULTADO FINAL ===")
        print(f"Total trades encontrados: {len(all_trades_found)}")
        
        if all_trades_found:
            timestamps = [t['timestamp'] for t in all_trades_found if t.get('timestamp')]
            if timestamps:
                by_month = {}
                for ts in timestamps:
                    dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc)
                    month = dt.strftime('%Y-%m')
                    by_month[month] = by_month.get(month, 0) + 1
                
                print(f"\nDistribución por mes:")
                for month, count in sorted(by_month.items()):
                    print(f"  {month}: {count}")
                
                oldest = datetime.fromtimestamp(min(timestamps)/1000, tz=timezone.utc)
                print(f"\nTrade más antiguo: {oldest.strftime('%Y-%m-%d')}")
                
                if oldest.year < 2026:
                    print("\n>>> ¡HAY TRADES DE 2025! El problema es que no los estamos capturando correctamente.")
                else:
                    print("\n>>> Todos los trades son de 2026. La API de BingX tiene limitación de retención.")

if __name__ == "__main__":
    asyncio.run(test_all_endpoints())
