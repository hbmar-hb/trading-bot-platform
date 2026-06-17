import sys
sys.path.insert(0, "/app")
from app.services.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    # Find the ENA signal at 19:04
    r = db.execute(text("""
        SELECT id, ticker, timeframe, direction, score, quality_tier, features, created_at
        FROM ai_signals
        WHERE ticker = 'ENAUSDT' AND created_at BETWEEN '2026-06-05 19:00:00' AND '2026-06-05 19:10:00'
        ORDER BY created_at
    """))
    print("ENA signals around 19:04:")
    for row in r.fetchall():
        print(f"  {row.id} {row.direction} score={row.score} tier={row.quality_tier} tf={row.timeframe}")
        
    # Bot logs for ENA bot around that time
    r2 = db.execute(text("""
        SELECT event_type, message, created_at
        FROM bot_logs
        WHERE created_at BETWEEN '2026-06-05 19:00:00' AND '2026-06-05 19:15:00'
          AND message LIKE '%ENA%'
        ORDER BY created_at
    """))
    print("\nBot logs mentioning ENA 19:00-19:15:")
    for row in r2.fetchall():
        msg = (row.message or "")[:100]
        print(f"  {row.created_at.strftime('%H:%M')} {row.event_type:25s} {msg}")
