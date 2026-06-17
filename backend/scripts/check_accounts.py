import sys
sys.path.insert(0, "/app")
from app.services.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    # All exchange accounts
    r = db.execute(text("""
        SELECT id, exchange, label, is_active, created_at
        FROM exchange_accounts
        ORDER BY created_at
    """))
    print("Exchange accounts:")
    for row in r.fetchall():
        print(f"  {row.id} {row.exchange:10s} {row.label:20s} active={row.is_active}")
    
    # Bots per account
    r2 = db.execute(text("""
        SELECT ea.label, COUNT(bc.id) as bot_count,
               SUM(CASE WHEN bc.ai_signal_mode THEN 1 ELSE 0 END) as ai_count
        FROM exchange_accounts ea
        LEFT JOIN bot_configs bc ON bc.exchange_account_id = ea.id AND bc.status = 'active'
        GROUP BY ea.id, ea.label
    """))
    print("\nBots per account:")
    for row in r2.fetchall():
        print(f"  {row.label:20s} total_bots={row.bot_count} ai_bots={row.ai_count}")
