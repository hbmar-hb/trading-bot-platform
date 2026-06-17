#!/usr/bin/env python3
"""
Monitor script for AI scanner health.
Run manually or via cron every 2 hours to verify the scanner is generating
quality signals and activations are flowing.

Usage:
    python scripts/monitor_scanner.py
    
Exit code:
    0 = healthy (signals present, activations happening)
    1 = warning (low signal count or quality issues)
    2 = critical (no signals or no activations)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.database import SessionLocal
from sqlalchemy import text


def main() -> int:
    now = datetime.now(timezone.utc)
    lookback_2h = now - timedelta(hours=2)
    lookback_24h = now - timedelta(hours=24)

    with SessionLocal() as db:
        # --- Last 2h signals ---
        r = db.execute(
            text("""
                SELECT ticker, timeframe, direction, score, quality_tier,
                       features->>'entry_type' as entry_type,
                       created_at
                FROM ai_signals
                WHERE created_at > :since
                ORDER BY created_at DESC
            """),
            {"since": lookback_2h},
        )
        signals_2h = r.fetchall()

        # --- Last 24h aggregation ---
        r2 = db.execute(
            text("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE quality_tier = 'STRONG') as strong,
                    COUNT(*) FILTER (WHERE quality_tier = 'MODERATE') as moderate,
                    COUNT(*) FILTER (WHERE quality_tier = 'WEAK') as weak,
                    ROUND(AVG(score)::numeric, 1) as avg_score,
                    COUNT(*) FILTER (WHERE features->>'entry_type' = 'CE') as ce_count,
                    COUNT(*) FILTER (WHERE features->>'entry_type' = 'RE') as re_count
                FROM ai_signals
                WHERE created_at > :since
            """),
            {"since": lookback_24h},
        )
        agg = r2.fetchone()

        # --- Open positions (active trades) ---
        r3 = db.execute(
            text("""
                SELECT symbol, side, quantity, unrealized_pnl, realized_pnl
                FROM positions WHERE status = 'open'
                ORDER BY symbol
            """)
        )
        open_pos = r3.fetchall()

        # --- Recent bot activations / rejections ---
        r4 = db.execute(
            text("""
                SELECT event_type, message, created_at
                FROM bot_logs
                WHERE created_at > :since
                  AND event_type IN (
                      'position_opened', 'signal_rejected',
                      'portfolio_risk_blocked', 'direction_flip_scoring'
                  )
                ORDER BY created_at DESC
                LIMIT 15
            """),
            {"since": lookback_2h},
        )
        bot_logs = r4.fetchall()

    # ── Report ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f" SCANNER HEALTH CHECK  |  {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    print(f"\n📊 Last 24h Signals: {agg.total}  (STRONG={agg.strong}, MODERATE={agg.moderate}, WEAK={agg.weak})")
    print(f"   Avg Score: {agg.avg_score}  |  CE={agg.ce_count}  RE={agg.re_count}")

    print(f"\n📡 Last 2h Signals ({len(signals_2h)}):")
    if signals_2h:
        for s in signals_2h[:10]:
            et = s.entry_type or "None"
            print(f"   {s.created_at.strftime('%H:%M')}  {s.ticker:12s} {s.timeframe:4s} {s.direction:5s} "
                  f"score={s.score:5.1f} {s.quality_tier:8s} {et}")
        if len(signals_2h) > 10:
            print(f"   ... and {len(signals_2h)-10} more")
    else:
        print("   ⚠️  NO SIGNALS in last 2 hours!")

    print(f"\n💼 Open Positions ({len(open_pos)}):")
    if open_pos:
        total_pnl = 0.0
        for p in open_pos:
            upnl = float(p.unrealized_pnl or 0)
            rpnl = float(p.realized_pnl or 0)
            total_pnl += upnl + rpnl
            print(f"   {p.symbol:16s} {p.side:5s} qty={p.quantity:10s} "
                  f"uP&L={upnl:+.4f}  rP&L={rpnl:+.4f}")
        print(f"   Total P&L (open): {total_pnl:+.4f}")
    else:
        print("   No open positions")

    print(f"\n🤖 Recent Bot Logs ({len(bot_logs)}):")
    if bot_logs:
        for log in bot_logs[:10]:
            msg = (log.message or "")[:70]
            print(f"   {log.created_at.strftime('%H:%M')}  {log.event_type:25s}  {msg}")
    else:
        print("   No relevant bot logs in last 2h")

    # ── Health verdict ──────────────────────────────────────────────────
    print(f"\n{'='*60}")
    status = "✅ HEALTHY"
    exit_code = 0

    if len(signals_2h) == 0:
        status = "🔴 CRITICAL: No signals in last 2h — scanner may be stuck!"
        exit_code = 2
    elif len(signals_2h) < 3:
        status = "🟡 WARNING: Very few signals in last 2h"
        exit_code = 1
    elif agg.avg_score and float(agg.avg_score) < 50:
        status = "🟡 WARNING: Avg score below 50 — check confluence weights"
        exit_code = 1

    print(status)
    print(f"{'='*60}\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
