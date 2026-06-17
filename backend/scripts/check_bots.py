import sys
sys.path.insert(0, "/app")
from app.services.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    r = db.execute(text("""
        SELECT bc.bot_name, bc.symbol, bc.timeframe, bc.ai_signal_mode,
               ea.exchange, ea.label
        FROM bot_configs bc
        LEFT JOIN exchange_accounts ea ON bc.exchange_account_id = ea.id
        WHERE bc.status = 'active'
        ORDER BY bc.ai_signal_mode DESC, bc.symbol
    """))
    print("Active bots by account:")
    for row in r.fetchall():
        ai = "AI" if row.ai_signal_mode else "MANUAL"
        print(f"  {ai:6s} {row.bot_name:20s} {row.symbol:15s} {row.timeframe:4s}  acct={row.label}")

    # Watchlist items
    r2 = db.execute(text("""
        SELECT symbol, timeframe, COUNT(*) as cnt
        FROM ai_watchlist
        GROUP BY symbol, timeframe
        ORDER BY cnt DESC
    """))
    print("\nWatchlist items:")
    for row in r2.fetchall():
        print(f"  {row.symbol:15s} {row.timeframe:4s}  users={row.cnt}")
