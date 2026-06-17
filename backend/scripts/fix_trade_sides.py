"""
Script para corregir el campo 'side' de trades sincronizados desde BingX.
El bug: bingx.py usaba o.get("side") (BUY/SELL de la orden) en lugar de
info.get("positionSide") (LONG/SHORT de la posición). Como las órdenes de
cierre son del lado opuesto a la posición, todos los trades tienen el side invertido.

Este script:
1. Lee raw_data de cada trade
2. Busca 'positionSide': 'LONG' o 'positionSide': 'SHORT'
3. Actualiza el campo side en la DB
"""
import asyncio
import sys
from sqlalchemy import select, update

sys.path.insert(0, '/app')
from app.services.database import AsyncSessionLocal
from app.models.exchange_trade import ExchangeTrade


async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExchangeTrade).where(ExchangeTrade.raw_data.isnot(None))
        )
        trades = result.scalars().all()
        
        updated = 0
        skipped = 0
        errors = 0
        
        for t in trades:
            raw = t.raw_data if t.raw_data else ""
            
            if "'positionSide': 'LONG'" in raw:
                correct_side = "long"
            elif "'positionSide': 'SHORT'" in raw:
                correct_side = "short"
            else:
                skipped += 1
                continue
            
            if t.side == correct_side:
                skipped += 1
                continue
            
            try:
                await db.execute(
                    update(ExchangeTrade)
                    .where(ExchangeTrade.id == t.id)
                    .values(side=correct_side)
                )
                updated += 1
                print(f"Updated: {t.exchange_trade_id} {t.symbol} {t.side} -> {correct_side}")
            except Exception as e:
                errors += 1
                print(f"ERROR: {t.exchange_trade_id} - {e}")
        
        await db.commit()
        print(f"\nDone. Updated: {updated}, Skipped: {skipped}, Errors: {errors}")


if __name__ == "__main__":
    asyncio.run(main())
