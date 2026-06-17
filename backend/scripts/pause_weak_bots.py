import sys
sys.path.insert(0, "/app")
from app.services.database import SessionLocal
from sqlalchemy import text

# Top 8 bots by signal count (resolved) in their specific timeframe
TOP_8 = [
    "XRPbot_15m",      # XRPUSDT 15m = 1376
    "PepBot_15m",      # 1000PEPEUSDT 15m = 1255
    "PENGUbot_15m",    # PENGUUSDT 15m = 1160
    "DOGEbot_15m",     # DOGEUSDT 15m = 1106
    "Ondo_sell/buy side_15m",  # ONDOUSDT 15m = 1085
    "ARBbot_15m",      # ARBUSDT 15m = 1057
    "FARTCBot_15m",    # FARTCOINUSDT 15m = 906
    "BTCbot_15m",      # BTCUSDT 15m = 652
]

with SessionLocal() as db:
    r = db.execute(text("""
        SELECT id, bot_name, symbol, timeframe
        FROM bot_configs
        WHERE status = 'active' AND ai_signal_mode = true
    """))
    
    paused = 0
    kept = 0
    for bot in r.fetchall():
        if bot.bot_name in TOP_8:
            print(f"KEEP: {bot.bot_name} ({bot.symbol} {bot.timeframe})")
            kept += 1
        else:
            print(f"PAUSE: {bot.bot_name} ({bot.symbol} {bot.timeframe})")
            db.execute(text("""
                UPDATE bot_configs 
                SET status = 'paused'
                WHERE id = :bot_id
            """), {"bot_id": bot.id})
            paused += 1
    
    db.commit()
    print(f"\nPaused: {paused} bots | Kept: {kept} bots")
