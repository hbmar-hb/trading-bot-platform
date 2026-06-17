import asyncio
import sys
sys.path.insert(0, '/app')
from app.services.database import AsyncSessionLocal
from app.models.exchange_trade import ExchangeTrade
from sqlalchemy import select, func
import ast

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExchangeTrade).where(ExchangeTrade.raw_data.isnot(None))
        )
        trades = result.scalars().all()
        stats = {'LONG': 0, 'SHORT': 0, 'BOTH': 0, 'missing': 0, 'parse_err': 0}
        mismatches = []
        for t in trades:
            raw = t.raw_data if t.raw_data else ""
            try:
                d = ast.literal_eval(raw)
                pos_side = d.get('positionSide', '').upper()
            except Exception:
                pos_side = 'parse_err'
            
            if pos_side in stats:
                stats[pos_side] += 1
            else:
                stats['missing'] += 1
                
            # Verificar si coincide con DB side
            if pos_side in ('LONG', 'SHORT'):
                expected = 'long' if pos_side == 'LONG' else 'short'
                if t.side != expected:
                    mismatches.append((t.id, t.symbol, t.side, expected, pos_side))
        
        print(f"Stats: {stats}")
        print(f"Mismatches: {len(mismatches)}")
        for m in mismatches[:10]:
            print(f"  ID={m[0]} {m[1]} DB={m[2]} expected={m[3]} positionSide={m[4]}")

asyncio.run(main())
