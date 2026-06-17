"""
Tarea Celery periódica para optimizar setups Monte Carlo de bots activos.

Se ejecuta cada 6 horas y optimiza los parámetros de las estrategias MC
basándose en backtests recientes. Solo optimiza si hay ≥5 trades nuevos
desde la última optimización.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger
from sqlalchemy import select

from app.services.database import SessionLocal
from app.models.bot_config import BotConfig
from app.models.exchange_trade import ExchangeTrade
from app.services.mc_optimizer import MCOptimizer


@shared_task(
    bind=True,
    max_retries=1,
    name="app.tasks.mc_optimizer_task.optimize_mc_setups",
    queue="default",
)
def optimize_mc_setups(self):
    """Optimizar todos los bots activos con setup MC habilitado."""
    try:
        return _run_optimization()
    except Exception as exc:
        logger.error(f"[MC OPTIMIZER TASK] Fatal error: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=300)


def _run_optimization() -> dict:
    with SessionLocal() as db:
        bots = (
            db.query(BotConfig)
            .filter(
                BotConfig.ai_signal_mode == True,
                BotConfig.status == "active",
            )
            .all()
        )

        optimized = 0
        skipped = 0
        errors = 0

        for bot in bots:
            mc_cfg = getattr(bot, "montecarlo_config", None) or {}
            if not mc_cfg.get("enabled") or mc_cfg.get("mode") != "setup_base":
                continue

            # Verificar si hay suficientes trades nuevos
            last_optimized_str = mc_cfg.get("last_optimized_at")
            last_optimized = None
            if last_optimized_str:
                try:
                    last_optimized = datetime.fromisoformat(last_optimized_str)
                    if last_optimized.tzinfo is None:
                        last_optimized = last_optimized.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            # Contar trades nuevos desde la última optimización
            new_trades_count = 0
            try:
                query = (
                    db.query(ExchangeTrade)
                    .filter(
                        ExchangeTrade.bot_id == bot.id,
                        ExchangeTrade.closed_at.is_not(None),
                    )
                )
                if last_optimized:
                    query = query.filter(ExchangeTrade.closed_at > last_optimized)
                new_trades_count = query.count()
            except Exception:
                pass

            # Solo optimizar si hay ≥5 trades nuevos o nunca se optimizó
            min_trades_for_optimization = 5
            if last_optimized and new_trades_count < min_trades_for_optimization:
                logger.debug(
                    f"[MC OPTIMIZER TASK] Skipping {bot.bot_name}: "
                    f"only {new_trades_count} new trades since last optimization"
                )
                skipped += 1
                continue

            # Ejecutar optimización
            try:
                result = MCOptimizer.optimize(bot, lookback_days=30, n_sims=1000)

                if "error" in result:
                    logger.warning(f"[MC OPTIMIZER TASK] {bot.bot_name}: {result['error']}")
                    errors += 1
                    continue

                # Solo aplicar si hay mejora significativa (>5%)
                if result.get("improvement_pct", 0) > 5:
                    MCOptimizer.apply_optimization(bot, result)
                    db.commit()
                    optimized += 1
                    logger.info(
                        f"[MC OPTIMIZER TASK] {bot.bot_name}: applied optimization "
                        f"(+{result['improvement_pct']:.1f}% fitness)"
                    )
                else:
                    logger.info(
                        f"[MC OPTIMIZER TASK] {bot.bot_name}: no significant improvement "
                        f"({result['improvement_pct']:.1f}%), skipping apply"
                    )
                    skipped += 1

            except Exception as exc:
                logger.error(f"[MC OPTIMIZER TASK] {bot.bot_name}: optimization failed: {exc}")
                errors += 1

        summary = {
            "optimized": optimized,
            "skipped": skipped,
            "errors": errors,
            "total_bots_checked": len(bots),
        }
        logger.info(f"[MC OPTIMIZER TASK] Summary: {summary}")
        return summary
