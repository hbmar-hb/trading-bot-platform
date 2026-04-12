"""
Verificar historial en TODOS los símbolos disponibles
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
        
        # Cargar todos los mercados
        print("\nCargando mercados...")
        markets = await exchange.load_markets()
        swap_symbols = [m['symbol'] for m in markets.values() if m.get('swap') and m.get('active') and 'USDT' in m['symbol']]
        print(f"Total símbolos USDT swap: {len(swap_symbols)}")
        
        # Buscar en todos los símbolos
        one_year_ago = int((time.time() - 365 * 24 * 3600) * 1000)
        
        print(f"\nBuscando trades en {len(swap_symbols)} símbolos...")
        print(f"(Esto puede tardar varios minutos)")
        
        all_trades = []
        symbols_with_trades = {}
        
        for i, sym in enumerate(swap_symbols):
            if i % 50 == 0:
                print(f"  Progreso: {i}/{len(swap_symbols)} símbolos revisados...")
            
            try:
                # Probar fetch_my_trades
                trades = await exchange.fetch_my_trades(sym, since=one_year_ago, limit=100)
                
                if trades:
                    count = len(trades)
                    symbols_with_trades[sym] = count
                    all_trades.extend(trades)
                    
                    # Mostrar el símbolo inmediatamente si tiene trades antiguos
                    timestamps = [t['timestamp'] for t in trades if t.get('timestamp')]
                    if timestamps:
                        oldest = min(timestamps)
                        oldest_dt = datetime.fromtimestamp(oldest/1000, tz=timezone.utc)
                        if oldest_dt.year < 2026:
                            print(f"    >>> {sym}: {count} trades, más antiguo: {oldest_dt.strftime('%Y-%m-%d')}")
                    
            except Exception as e:
                # Ignorar errores (símbolos sin trades, rate limits, etc.)
                pass
        
        await exchange.close()
        
        print(f"\n=== RESULTADOS ===")
        print(f"Total símbolos con trades: {len(symbols_with_trades)}")
        print(f"Total trades encontrados: {len(all_trades)}")
        
        if all_trades:
            # Analizar fechas
            timestamps = [t['timestamp'] for t in all_trades if t.get('timestamp')]
            if timestamps:
                oldest = datetime.fromtimestamp(min(timestamps)/1000, tz=timezone.utc)
                newest = datetime.fromtimestamp(max(timestamps)/1000, tz=timezone.utc)
                
                print(f"\nFecha más antigua: {oldest.strftime('%Y-%m-%d %H:%M')}")
                print(f"Fecha más reciente: {newest.strftime('%Y-%m-%d %H:%M')}")
                
                # Distribución por año-mes
                by_month = {}
                for ts in timestamps:
                    dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc)
                    month = dt.strftime('%Y-%m')
                    by_month[month] = by_month.get(month, 0) + 1
                
                print(f"\nTrades por mes:")
                for month, count in sorted(by_month.items()):
                    print(f"  {month}: {count}")
                
                # Top símbolos
                print(f"\nTop 10 símbolos con más trades:")
                for sym, count in sorted(symbols_with_trades.items(), key=lambda x: -x[1])[:10]:
                    print(f"  {sym}: {count}")
        
        print(f"\n=== CONCLUSIÓN ===")
        if not all_trades:
            print("No se encontraron trades en ningún símbolo.")
        elif min(timestamps)/1000 < time.time() - 180*24*3600:
            print("¡Hay trades de más de 6 meses! El problema es la limitación de símbolos.")
        else:
            print("Todos los trades son recientes (menos de 6 meses).")
            print("Posiblemente BingX solo retiene 3-6 meses de historial en la API.")

if __name__ == "__main__":
    asyncio.run(main())
