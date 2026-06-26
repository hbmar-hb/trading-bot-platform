"""Celery task — envía resumen del modo shadow a Telegram cada 4h.

El modo shadow evalúa cada señal contra perfiles de filtros sin ejecutar
posiciones, para validar ML y gates durante el test de 48h.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger
from sqlalchemy import text

from app.services.database import SessionLocal
from app.services.notifier import send_telegram_sync


_SUMMARY_HOURS = 4
_WINDOW_HOURS = 24

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
    since_window = now - timedelta(hours=_WINDOW_HOURS)

    with SessionLocal() as db:
        # Totales por perfil en la ventana de 24h
        profile_totals = _query_all(
            db,
            """
            SELECT
                profile,
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE passed) as passed,
                COUNT(*) FILTER (WHERE NOT passed) as blocked,
                COUNT(*) FILTER (WHERE passed AND outcome IN ('SUCCESS', 'FAILURE_MAX_ADVERSE', 'FAILURE_BEHAVIORAL')) as resolved_passed,
                COUNT(*) FILTER (WHERE passed AND outcome = 'SUCCESS') as passed_then_success,
                COUNT(*) FILTER (WHERE passed AND outcome IN ('FAILURE_MAX_ADVERSE', 'FAILURE_BEHAVIORAL')) as passed_then_failure
            FROM ai_signal_shadow_evaluations
            WHERE evaluated_at >= :since
            GROUP BY profile
            ORDER BY profile
            """,
            {"since": since_window},
        )

        # Breakdown de gates bloqueantes en la ventana de 24h
        gate_breakdown = _query_all(
            db,
            """
            SELECT profile, blocked_at, COUNT(*) as count
            FROM ai_signal_shadow_evaluations
            WHERE evaluated_at >= :since
              AND NOT passed
              AND blocked_at IS NOT NULL
            GROUP BY profile, blocked_at
            ORDER BY profile, count DESC
            """,
            {"since": since_window},
        )

        # Señales evaluadas en las últimas 4h
        recent_evals = _query_one(
            db,
            """
            SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE passed) as passed
            FROM ai_signal_shadow_evaluations
            WHERE evaluated_at >= :since
            """,
            {"since": since_summary},
        )

        # Comparativa ML vs heurístico puro en shadow (últimas 24h, score>=80 STRONG)
        ml_vs_heuristic = _query_all(
            db,
            """
            SELECT DISTINCT ON (ai_signal_id)
                ai_signal_id,
                anti_fake_status,
                success_probability,
                score,
                outcome
            FROM ai_signal_shadow_evaluations
            WHERE evaluated_at >= :since
              AND score >= 80
              AND quality_tier = 'STRONG'
            ORDER BY ai_signal_id, evaluated_at DESC
            """,
            {"since": since_window},
        )

    # Análisis ML vs heurístico
    heuristic_accepts = 0
    ml_blocks = 0
    ml_block_then_success = 0
    ml_block_then_failure = 0
    ml_caution = 0
    ml_caution_then_success = 0
    ml_caution_then_failure = 0
    ml_clear = 0
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
        else:
            ml_clear += 1
            if is_success:
                ml_clear_then_success += 1
            else:
                ml_clear_then_failure += 1

    lines = [
        f"📊 <b>Resumen Shadow Mode</b> (últimas {_SUMMARY_HOURS}h)",
        f"<b>Objetivo:</b> validar ML + gates sin ejecutar trades",
        "",
        f"<b>Evaluaciones recientes (4h):</b> {recent_evals['total'] or 0} (pasaron {recent_evals['passed'] or 0})",
        "",
        f"<b>Por perfil (24h):</b>",
    ]

    if profile_totals:
        for r in profile_totals:
            lines.append(
                f"  <b>{r['profile']}</b>: total {r['total']}, pasaron {r['passed']}, "
                f"bloqueadas {r['blocked']}"
            )
            if r["resolved_passed"]:
                lines.append(
                    f"    resueltas que pasaron: {r['resolved_passed']} "
                    f"(SUCCESS {r['passed_then_success']}, FAILURE {r['passed_then_failure']})"
                )
    else:
        lines.append("  Sin evaluaciones en las últimas 24h.")

    lines.append("")
    lines.append("<b>Gates bloqueantes (24h):</b>")
    if gate_breakdown:
        current_profile = None
        for r in gate_breakdown:
            if r["profile"] != current_profile:
                current_profile = r["profile"]
                lines.append(f"  <b>{current_profile}</b>")
            lines.append(f"    {r['blocked_at']}: {r['count']}")
    else:
        lines.append("  Ninguno")

    lines.extend([
        "",
        "<b>ML vs Heurístico puro (24h, shadow score≥80 STRONG):</b>",
        f"  Heurístico aceptaría: {heuristic_accepts}",
        f"  ML bloquea: {ml_blocks} ({ml_block_then_success} SUCCESS, {ml_block_then_failure} FAILURE)",
        f"  ML pone CAUTION: {ml_caution} ({ml_caution_then_success} SUCCESS, {ml_caution_then_failure} FAILURE)",
        f"  ML mantiene CLEAR: {ml_clear} ({ml_clear_then_success} SUCCESS, {ml_clear_then_failure} FAILURE)",
    ])

    if heuristic_accepts > 0 and ml_blocks > 0:
        false_positive_reduction = ml_block_then_failure / max(ml_blocks, 1)
        lines.append(
            f"  De las que ML bloquea, {false_positive_reduction:.0%} fueron FAILURE → ML filtra basura"
        )

    lines.append("")
    lines.append(f"<i>Generado: {now.strftime('%Y-%m-%d %H:%M UTC')}</i>")

    return {
        "status": "ok",
        "message": "\n".join(lines),
    }


@shared_task(
    name="app.tasks.monitor_ai_shadow_task.run_monitor",
    queue="default",
    max_retries=1,
    default_retry_delay=60,
)
def run_monitor() -> dict:
    try:
        summary = build_summary()
        if summary["status"] == "error":
            send_telegram_sync(f"⚠️ {summary['message']}", level="essential")
            logger.warning(f"[MONITOR_AI_SHADOW] {summary['message']}")
            return summary

        send_telegram_sync(summary["message"], level="essential")
        logger.info("[MONITOR_AI_SHADOW] Resumen enviado a Telegram")
        return summary
    except Exception as exc:
        logger.error(f"[MONITOR_AI_SHADOW] Error: {exc}", exc_info=True)
        send_telegram_sync(f"⚠️ Error en monitor shadow: {exc}", level="essential")
        raise
