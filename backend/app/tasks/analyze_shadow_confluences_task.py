"""Daily shadow-mode confluence analysis.

Runs every 24h, queries resolved shadow evaluations grouped by timeframe and
confluence features, and sends a Telegram summary with the best combinations.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger
from sqlalchemy import text

from app.services.database import SessionLocal
from app.services.notifier import send_telegram_sync


_LOOKBACK_DAYS = 30
_MIN_SAMPLES = 5


_QUERY = """
SELECT
    timeframe,
    features_snapshot->>'has_ob' AS ob,
    features_snapshot->>'has_killzone' AS killzone,
    features_snapshot->>'htf_aligned' AS htf,
    features_snapshot->>'fvg_count' AS fvg,
    features_snapshot->>'structure_type' AS structure,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE outcome = 'SUCCESS') AS wins,
    ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'SUCCESS') / NULLIF(COUNT(*), 0), 2) AS wr,
    ROUND(AVG(pnl_pct)::numeric, 4) AS avg_pnl
FROM ai_signal_shadow_evaluations
WHERE profile = 'bot_match'
  AND passed = true
  AND evaluated_at >= NOW() - INTERVAL ':lookback_days days'
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY wr DESC, avg_pnl DESC
LIMIT 50;
"""


@shared_task(
    bind=True,
    max_retries=1,
    name="app.tasks.analyze_shadow_confluences_task.run_analysis",
    queue="default",
)
def run_analysis(self) -> dict:
    try:
        return _run_analysis_sync()
    except Exception as exc:
        logger.error(f"[SHADOW ANALYSIS] failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=300)


def _run_analysis_sync() -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            text(_QUERY), {"lookback_days": _LOOKBACK_DAYS}
        ).mappings().all()

    if not rows:
        return {"status": "no_data", "rows": 0}

    # Filter out combinations with too few samples
    filtered = [r for r in rows if r["total"] >= _MIN_SAMPLES]

    lines = [
        f"📊 <b>Shadow Confluence Analysis</b>\n",
        f"Perfil: <code>bot_match</code> | Lookback: {_LOOKBACK_DAYS}d | Min samples: {_MIN_SAMPLES}",
        f"Generado: {datetime.now(timezone.utc).isoformat()[:19]} UTC\n",
        "<pre>",
        f"{'TF':<6} {'OB':<5} {'KZ':<5} {'HTF':<5} {'FVG':<4} {'STR':<7} {'N':<4} {'WINS':<5} {'WR%':<7} {'AVG PNL':<9}",
        "-" * 70,
    ]

    for r in filtered[:30]:
        lines.append(
            f"{r['timeframe']:<6} "
            f"{str(r['ob']):<5} "
            f"{str(r['killzone']):<5} "
            f"{str(r['htf']):<5} "
            f"{str(r['fvg']):<4} "
            f"{r['structure'] or 'none':<7} "
            f"{r['total']:<4} "
            f"{r['wins']:<5} "
            f"{r['wr']:<7} "
            f"{r['avg_pnl']:<9}"
        )

    if not filtered:
        lines.append("No combinations with enough samples yet.")

    lines.append("</pre>")
    message = "\n".join(lines)

    try:
        send_telegram_sync(message, level="essential")
    except Exception as notify_exc:
        logger.warning(f"[SHADOW ANALYSIS] Telegram failed: {notify_exc}")

    logger.info(f"[SHADOW ANALYSIS] sent summary with {len(filtered)} combinations")
    return {"status": "ok", "rows": len(filtered)}
