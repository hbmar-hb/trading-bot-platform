import sys
sys.path.insert(0, "/app")
from app.services.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    r = db.execute(text("""
        SELECT 
            bc.bot_name,
            bc.symbol,
            bc.timeframe,
            COUNT(s.id) as total_signals,
            COUNT(s.id) FILTER (WHERE s.outcome IS NOT NULL) as resolved_signals,
            COUNT(s.id) FILTER (WHERE s.outcome = 'SUCCESS') as wins,
            COUNT(s.id) FILTER (WHERE s.outcome IN ('FAILURE_MAX_ADVERSE', 'FAILURE_BEHAVIORAL')) as losses
        FROM bot_configs bc
        LEFT JOIN positions p ON p.bot_id = bc.id
        LEFT JOIN ai_signals s ON s.id = CAST(p.extra_config->>'ai_signal_id' AS UUID)
        WHERE bc.status = 'active' AND bc.ai_signal_mode = true
        GROUP BY bc.id, bc.bot_name, bc.symbol, bc.timeframe
        ORDER BY resolved_signals DESC
    """))
    print("Bot samples (from positions linked to signals):")
    for row in r.fetchall():
        wr = f"{row.wins/(row.wins+row.losses)*100:.0f}%" if (row.wins+row.losses) > 0 else "N/A"
        print(f"  {row.bot_name:20s} {row.symbol:15s} {row.timeframe:4s}  total={row.total_signals:4d} resolved={row.resolved_signals:4d} W={row.wins:3d} L={row.losses:3d} WR={wr}")

    # Also check direct signal counts per ticker/tf
    r2 = db.execute(text("""
        SELECT 
            ticker,
            timeframe,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE outcome IS NOT NULL) as resolved,
            COUNT(*) FILTER (WHERE outcome = 'SUCCESS') as wins,
            COUNT(*) FILTER (WHERE outcome IN ('FAILURE_MAX_ADVERSE', 'FAILURE_BEHAVIORAL')) as losses
        FROM ai_signals
        WHERE created_at > NOW() - INTERVAL '90 days'
        GROUP BY ticker, timeframe
        ORDER BY resolved DESC
    """))
    print("\nSignals by ticker/timeframe (last 90d):")
    for row in r2.fetchall():
        wr = f"{row.wins/(row.wins+row.losses)*100:.0f}%" if (row.wins+row.losses) > 0 else "N/A"
        print(f"  {row.ticker:15s} {row.timeframe:4s}  total={row.total:4d} resolved={row.resolved:4d} W={row.wins:3d} L={row.losses:3d} WR={wr}")
