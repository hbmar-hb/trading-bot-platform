"""Celery task — envía resumen del bot IA en paper a Telegram cada 4h.

Esta tarea NO mide rentabilidad. Mide si el sistema funciona y si el ML
aporta valor sobre las heurísticas puras.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger
from sqlalchemy import text

from app.services.database import SessionLocal
from app.services.notifier import send_telegram_sync


_BOT_NAME = "BTCbot_4h_AI_Paper"
_SUMMARY_HOURS = 4
_ALERT_HOURS = 24

# Umbrales de _effective_status en bot_activator.py
_ML_BLOCK_THR = 0.30
_ML_CAUTION_THR = 0.50


def _query_one(db, sql: str, params: dict | None = None):
    result = db.execute(text(sql), params or {})
    return result.mappings().one_or_none()


def _query_all(db, sql: str, params: dict | None = None):
    result = db.execute(text(sql), params or {})
    return result.mappings().all()


def _effective_status(anti_fake_status: str | None, success_probability: float | None) -> str:
    """Réplica ligera de bot_activator._effective_status."""
    if success_probability is None:
        return anti_fake_status or "CLEAR"
    if success_probability <= _ML_BLOCK_THR:
        return "BLOCK"
    if success_probability <= _ML_CAUTION_THR:
        return "CAUTION"
    return "CLEAR"


def build_summary() -> dict:
    now = datetime.now(timezone.utc)
    since_summary = now - timedelta(hours=_SUMMARY_HOURS)
    since_alert = now - timedelta(hours=_ALERT_HOURS)

    with SessionLocal() as db:
        bot = _query_one(
            db,
            """
            SELECT id, bot_name, status, ai_signal_mode, paper_balance_id
            FROM bot_configs
            WHERE bot_name = :bot_name
            """,
            {"bot_name": _BOT_NAME},
        )
        if not bot:
            return {"status": "error", "message": f"Bot {_BOT_NAME} no encontrado"}

        bot_id = str(bot["id"])

        # Señales generadas en las últimas 4h
        signals = _query_one(
            db,
            """
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN quality_tier = 'STRONG' THEN 1 END) as strong,
                COUNT(CASE WHEN quality_tier = 'MODERATE' THEN 1 END) as moderate,
                COUNT(CASE WHEN quality_tier = 'CAUTION' THEN 1 END) as caution,
                COUNT(CASE WHEN anti_fake_status = 'CLEAR' THEN 1 END) as clear,
                COUNT(CASE WHEN anti_fake_status = 'CAUTION' THEN 1 END) as caution_status,
                COUNT(CASE WHEN anti_fake_status = 'BLOCK' THEN 1 END) as block,
                AVG(score) as avg_score,
                MAX(score) as max_score
            FROM ai_signals
            WHERE ticker = 'BTCUSDT'
              AND timeframe = '4h'
              AND created_at >= :since
            """,
            {"since": since_summary},
        )

        # Distribución de scores en las últimas 24h (diagnóstico)
        score_distribution = _query_one(
            db,
            """
            SELECT
                COUNT(*) as total_24h,
                COUNT(CASE WHEN score >= 60 THEN 1 END) as gte_60,
                COUNT(CASE WHEN score >= 70 THEN 1 END) as gte_70,
                COUNT(CASE WHEN score >= 75 THEN 1 END) as gte_75,
                COUNT(CASE WHEN score >= 80 THEN 1 END) as gte_80,
                COUNT(CASE WHEN score >= 60 AND quality_tier = 'STRONG' AND anti_fake_status = 'CLEAR' THEN 1 END) as strong_clear_60,
                COUNT(CASE WHEN score >= 70 AND quality_tier = 'STRONG' AND anti_fake_status = 'CLEAR' THEN 1 END) as strong_clear_70,
                COUNT(CASE WHEN score >= 75 AND quality_tier = 'STRONG' AND anti_fake_status = 'CLEAR' THEN 1 END) as strong_clear_75
            FROM ai_signals
            WHERE ticker = 'BTCUSDT'
              AND timeframe = '4h'
              AND created_at >= :since
            """,
            {"since": since_alert},
        )

        # Señales que pasan TODOS los filtros del bot en las últimas 24h
        passed_all = _query_one(
            db,
            """
            SELECT COUNT(*) as count
            FROM ai_signals s
            WHERE s.ticker = 'BTCUSDT'
              AND s.timeframe = '4h'
              AND s.created_at >= :since
              AND s.quality_tier = 'STRONG'
              AND s.anti_fake_status = 'CLEAR'
              AND s.score >= 80
            """,
            {"since": since_alert},
        )

        # Comparativa ML vs heurístico puro
        # Heurístico puro = score>=80, STRONG, anti_fake_status=CLEAR
        # Con ML = mismo score/tier pero status ajustado por success_probability
        ml_vs_heuristic = _query_all(
            db,
            """
            SELECT
                s.outcome,
                s.anti_fake_status,
                s.success_probability,
                s.score,
                s.pnl_pct
            FROM ai_signals s
            WHERE s.ticker = 'BTCUSDT'
              AND s.timeframe = '4h'
              AND s.created_at >= :since
              AND s.score >= 80
              AND s.quality_tier = 'STRONG'
              AND s.outcome IN ('SUCCESS', 'FAILURE_MAX_ADVERSE', 'FAILURE_BEHAVIORAL')
            ORDER BY s.created_at DESC
            """,
            {"since": since_alert},
        )

        # Rechazos del bot en las últimas 4h
        rejections = _query_all(
            db,
            """
            SELECT event_type, COUNT(*) as count
            FROM bot_logs
            WHERE bot_id = :bot_id
              AND created_at >= :since
              AND event_type IN ('cost_gate_blocked', 'slippage_abort', 'regime_blocked', 'ai_signal_rejected', 'score_rejected', 'tier_rejected')
            GROUP BY event_type
            """,
            {"bot_id": bot_id, "since": since_summary},
        )

        # Posiciones ejecutadas por el bot
        positions = _query_one(
            db,
            """
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN status = 'open' THEN 1 END) as open,
                COUNT(CASE WHEN status = 'closed' THEN 1 END) as closed,
                SUM(CASE WHEN status = 'closed' THEN realized_pnl ELSE 0 END) as pnl_closed,
                SUM(CASE WHEN status = 'open' THEN unrealized_pnl ELSE 0 END) as pnl_open
            FROM positions
            WHERE bot_id = :bot_id
              AND opened_at >= :since
            """,
            {"bot_id": bot_id, "since": since_summary},
        )

        # Régimen actual de BTC 4h — prefer ai_latest_scans (updated every scan)
        # and fall back to ai_signals when no scan row exists yet.
        regime_row = _query_one(
            db,
            """
            SELECT
                context->>'market_regime' as regime,
                context->>'regime_adx' as adx,
                context->>'regime_atr_p' as atr_p,
                status as scan_status,
                context->>'reason' as scan_reason,
                scanned_at
            FROM ai_latest_scans
            WHERE symbol = 'BTCUSDT' AND timeframe = '4h'
            ORDER BY scanned_at DESC
            LIMIT 1
            """,
        )
        if not regime_row or not regime_row["regime"]:
            regime_row = _query_one(
                db,
                """
                SELECT features->>'market_regime' as regime,
                       features->>'regime_adx' as adx,
                       features->>'regime_atr_p' as atr_p,
                       NULL as scan_status,
                       NULL as scan_reason,
                       created_at as scanned_at
                FROM ai_signals
                WHERE ticker = 'BTCUSDT' AND timeframe = '4h'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                {"since": since_summary},
            )

    # Análisis ML vs heurístico
    heuristic_accepts = 0
    ml_blocks = 0
    ml_caution = 0
    ml_clear = 0
    ml_block_then_success = 0
    ml_block_then_failure = 0
    ml_caution_then_success = 0
    ml_caution_then_failure = 0
    ml_clear_then_success = 0
    ml_clear_then_failure = 0

    for row in ml_vs_heuristic:
        is_heuristic_clear = row["anti_fake_status"] == "CLEAR"
        ml_status = _effective_status(row["anti_fake_status"], row["success_probability"])
        is_success = row["outcome"] == "SUCCESS"

        if is_heuristic_clear:
            heuristic_accepts += 1

        if ml_status == "BLOCK":
            ml_blocks += 1
            if is_success:
                ml_block_then_success += 1
            else:
                ml_block_then_failure += 1
        elif ml_status == "CAUTION":
            ml_caution += 1
            if is_success:
                ml_caution_then_success += 1
            else:
                ml_caution_then_failure += 1
        else:  # CLEAR
            ml_clear += 1
            if is_success:
                ml_clear_then_success += 1
            else:
                ml_clear_then_failure += 1

    lines = [
        f"📊 <b>Resumen {_BOT_NAME}</b> (últimas {_SUMMARY_HOURS}h)",
        f"🤖 Estado: {bot['status']} | AI mode: {bot['ai_signal_mode']}",
        "",
        "<b>Objetivo:</b> test de infraestructura + valor del ML",
        "",
        "<b>Señales BTC 4h generadas (4h):</b>",
        f"  Total: {signals['total'] or 0}",
        f"  STRONG: {signals['strong'] or 0} | MODERATE: {signals['moderate'] or 0} | CAUTION: {signals['caution'] or 0}",
        f"  CLEAR: {signals['clear'] or 0} | CAUTION: {signals['caution_status'] or 0} | BLOCK: {signals['block'] or 0}",
        f"  Score avg/max: {(signals['avg_score'] or 0):.1f}/{(signals['max_score'] or 0):.1f}",
        "",
        "<b>Diagnóstico scores (24h):</b>",
        f"  Generadas: {score_distribution['total_24h'] or 0}",
        f"  score≥60: {score_distribution['gte_60'] or 0}",
        f"  score≥70: {score_distribution['gte_70'] or 0}",
        f"  score≥75: {score_distribution['gte_75'] or 0}",
        f"  score≥80 (efectivo RANGING): {score_distribution['gte_80'] or 0}",
        f"  STRONG+CLEAR score≥60: {score_distribution['strong_clear_60'] or 0}",
        f"  STRONG+CLEAR score≥70: {score_distribution['strong_clear_70'] or 0}",
        f"  STRONG+CLEAR score≥75: {score_distribution['strong_clear_75'] or 0}",
        "",
        "<b>Señales que pasan TODOS los filtros (24h):</b>",
        f"  STRONG+CLEAR+score≥80: {passed_all['count'] or 0}",
    ]

    if (passed_all["count"] or 0) == 0:
        lines.extend([
            "",
            "⚠️ <b>ALERTA:</b> 24h sin señales que pasen todos los filtros.",
            "   Régimen hostil o filtros excesivamente estrictos.",
        ])

    # Comparativa ML vs heurístico
    lines.extend([
        "",
        "<b>ML vs Heurístico puro (24h, señales resueltas score≥80 STRONG):</b>",
        f"  Heurístico aceptaría: {heuristic_accepts}",
        f"  ML bloquea: {ml_blocks} ({ml_block_then_success} SUCCESS, {ml_block_then_failure} FAILURE)",
        f"  ML pone CAUTION: {ml_caution} ({ml_caution_then_success} SUCCESS, {ml_caution_then_failure} FAILURE)",
        f"  ML mantiene CLEAR: {ml_clear} ({ml_clear_then_success} SUCCESS, {ml_clear_then_failure} FAILURE)",
    ])

    if heuristic_accepts > 0 and ml_blocks > 0:
        false_positive_reduction = ml_block_then_failure / max(ml_blocks, 1)
        lines.append(f"  De las que ML bloquea, {false_positive_reduction:.0%} fueron FAILURE → ML filtra basura")

    lines.append("")
    lines.append("<b>Rechazos (4h):</b>")
    if rejections:
        for r in rejections:
            lines.append(f"  {r['event_type']}: {r['count']}")
    else:
        lines.append("  Ninguno")

    lines.extend([
        "",
        "<b>Posiciones:</b>",
        f"  Ejecutadas: {positions['total'] or 0} (abiertas {positions['open'] or 0}, cerradas {positions['closed'] or 0})",
        f"  PnL cerrado: {float(positions['pnl_closed'] or 0):.2f} USDT",
        f"  PnL abierto: {float(positions['pnl_open'] or 0):.2f} USDT",
    ])

    if regime_row and regime_row["regime"]:
        scan_info = ""
        if regime_row.get("scan_status"):
            scan_reason = regime_row.get("scan_reason") or "sin detalle"
            scanned_at = regime_row.get("scanned_at")
            scanned_str = scanned_at.strftime("%H:%M UTC") if scanned_at else "?"
            scan_info = f" | último scan {scanned_str}: {regime_row['scan_status']} ({scan_reason})"
        lines.extend([
            "",
            "<b>Régimen BTC 4h:</b>",
            f"  {regime_row['regime']} | ADX {float(regime_row['adx'] or 0):.1f} | ATRp {float(regime_row['atr_p'] or 0):.1f}{scan_info}",
        ])

    lines.append("")
    lines.append(f"<i>Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>")

    return {
        "status": "ok",
        "message": "\n".join(lines),
        "bot_id": bot_id,
        "signals_total": signals["total"] or 0,
        "passed_all_24h": passed_all["count"] or 0,
    }


@shared_task(
    name="app.tasks.monitor_ai_paper_task.run_monitor",
    queue="default",
    max_retries=1,
    default_retry_delay=60,
)
def run_monitor() -> dict:
    try:
        summary = build_summary()
        if summary["status"] == "error":
            send_telegram_sync(f"⚠️ {summary['message']}", level="essential")
            logger.warning(f"[MONITOR_AI_PAPER] {summary['message']}")
            return summary

        send_telegram_sync(summary["message"], level="essential")
        logger.info("[MONITOR_AI_PAPER] Resumen enviado a Telegram")
        return {
            "status": "ok",
            "signals_total": summary["signals_total"],
            "passed_all_24h": summary["passed_all_24h"],
        }
    except Exception as exc:
        logger.error(f"[MONITOR_AI_PAPER] Task failed: {exc}")
        try:
            send_telegram_sync(f"⚠️ Monitor AI paper falló: {exc}", level="essential")
        except Exception:
            pass
        return {"status": "error", "error": str(exc)}


if __name__ == "__main__":
    result = run_monitor()
    print(result)
