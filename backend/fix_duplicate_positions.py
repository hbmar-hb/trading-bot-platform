"""
Script para limpiar posiciones duplicadas.
Mantiene solo la posición más reciente por símbolo/bot.
"""
import asyncio
import os
import sys

sys.path.insert(0, '/app')
os.environ.setdefault("DATABASE_URL", "postgresql://admin:admin@postgres:5432/tradingbot")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from sqlalchemy import select, desc
from app.services.database import AsyncSessionLocal
from app.models.position import Position

async def fix_duplicates():
    async with AsyncSessionLocal() as db:
        # Buscar posiciones duplicadas (mismo símbolo, mismo bot, estado open)
        result = await db.execute(
            select(Position)
            .where(Position.status == "open")
            .order_by(desc(Position.opened_at))
        )
        
        positions = result.scalars().all()
        
        # Agrupar por símbolo + bot_id
        by_symbol_bot = {}
        for pos in positions:
            key = (pos.symbol, pos.bot_id)
            if key not in by_symbol_bot:
                by_symbol_bot[key] = []
            by_symbol_bot[key].append(pos)
        
        print(f"Total posiciones abiertas: {len(positions)}")
        print(f"Grupos únicos (símbolo+bot): {len(by_symbol_bot)}")
        print()
        
        to_close = []
        
        for (symbol, bot_id), group in by_symbol_bot.items():
            if len(group) > 1:
                print(f"⚠️  {symbol}: {len(group)} posiciones duplicadas")
                # Mantener la más reciente, marcar las demás como cerradas
                sorted_positions = sorted(group, key=lambda p: p.opened_at, reverse=True)
                keep = sorted_positions[0]
                duplicates = sorted_positions[1:]
                
                print(f"   ✅ Mantener: {keep.id} (creada: {keep.opened_at})")
                
                for dup in duplicates:
                    print(f"   ❌ Cerrar: {dup.id} (creada: {dup.opened_at})")
                    dup.status = "closed"
                    dup.closed_at = keep.opened_at  # Usar la fecha de la que se mantiene
                    dup.realized_pnl = 0  # No sabemos el PnL real
                    to_close.append(dup)
        
        if to_close:
            print(f"\n⚡ Cerrando {len(to_close)} posiciones duplicadas...")
            await db.commit()
            print("✅ Posiciones duplicadas cerradas correctamente")
        else:
            print("\n✅ No hay posiciones duplicadas")

if __name__ == "__main__":
    asyncio.run(fix_duplicates())
