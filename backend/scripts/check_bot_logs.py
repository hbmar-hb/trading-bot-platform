import sys
sys.path.insert(0, "/app")
from app.services.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    r = db.execute(text("""
        SELECT event_type, message, created_at 
        FROM bot_logs 
        WHERE created_at > NOW() - INTERVAL '2 hours'
        ORDER BY created_at DESC 
        LIMIT 30
    """))
    print("Bot logs last 2h:")
    for row in r.fetchall():
        msg = (row.message or "")[:80]
        print(f"  {row.created_at.strftime('%H:%M')} {row.event_type:25s} {msg}")
