import sys
sys.path.insert(0, "/app")
from app.services.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    # Check all active AI bots and their exchange account
    r = db.execute(text("""
        SELECT bot_name, symbol, timeframe, exchange_account_id, paper_balance_id,
               position_value, leverage, position_sizing_type
        FROM bot_configs
        WHERE status = 'active' AND ai_signal_mode = true
        ORDER BY symbol
    """))
    print("Active AI bots:")
    for row in r.fetchall():
        print(f"  {row.bot_name:20s} {row.symbol:15s} {row.timeframe:4s} "
              f"val={row.position_value} sizing={row.position_sizing_type} lev={row.leverage}")
