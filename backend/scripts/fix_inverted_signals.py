"""
Script de corrección: marca como INVALID las señales de IA con niveles invertidos.

Ejecutar dentro del contenedor backend:
    python scripts/fix_inverted_signals.py
"""
import os
import sys

# Añadir /app al path para imports
sys.path.insert(0, "/app")

from app.services.database import SessionLocal
from sqlalchemy import text


def main():
    db = SessionLocal()

    # Detectar LONGs con TP1 <= entry o SL >= entry
    long_query = text("""
        UPDATE ai_signals
        SET outcome = 'INVALID', pnl_pct = NULL
        WHERE direction = 'long'
          AND (take_profit_1 <= entry_price OR stop_loss >= entry_price)
          AND outcome != 'INVALID'
        RETURNING id
    """)

    # Detectar SHORTs con TP1 >= entry o SL <= entry
    short_query = text("""
        UPDATE ai_signals
        SET outcome = 'INVALID', pnl_pct = NULL
        WHERE direction = 'short'
          AND (take_profit_1 >= entry_price OR stop_loss <= entry_price)
          AND outcome != 'INVALID'
        RETURNING id
    """)

    long_result = db.execute(long_query)
    long_ids = long_result.fetchall()

    short_result = db.execute(short_query)
    short_ids = short_result.fetchall()

    db.commit()

    total = len(long_ids) + len(short_ids)
    print(f"[FIX] Señales LONG corregidas: {len(long_ids)}")
    print(f"[FIX] Señales SHORT corregidas: {len(short_ids)}")
    print(f"[FIX] TOTAL anomalías marcadas como INVALID: {total}")

    if total > 0:
        print("[FIX] IDs corregidos (primeros 20):")
        for row in (long_ids + short_ids)[:20]:
            print(f"  - {row[0]}")

    db.close()


if __name__ == "__main__":
    main()
