"""Task periódico: recalcula y persiste la configuración óptima para bots IA.

Ahora con dos modos de disparo:
  1. Periódico (Celery Beat cada hora): todos los bots
  2. Event-driven (tras cierre de posición AI): solo el bot afectado

Incluye throttle de 30 minutos por bot para evitar recalibraciones excesivas,
y guarda historial de cambios en ai_signal_config para auditoría.
"""
from datetime import datetime, timedelta, timezone

from celery import shared_task
from loguru import logger

from app.engines.bot_activator import _compute_optimal_config_sync
from app.models.bot_config import BotConfig
from app.services.database import SessionLocal

# Throttle: minimum minutes between recalibrations for the same bot
_MIN_RECHECK_MINUTES = 30


@shared_task(queue="default", name="app.tasks.ai_optimal_config_task.refresh_optimal_configs")
def refresh_optimal_configs(bot_id: str | None = None) -> dict:
    """Recalculate and persist optimal config for AI bots.

    Args:
        bot_id: If provided, only recalibrate this bot. If None, all AI bots.
    """
    with SessionLocal() as db:
        query = (
            db.query(BotConfig)
            .filter(
                BotConfig.ai_signal_mode.is_(True),
                BotConfig.ai_optimal_config_enabled.is_(True),
            )
        )
        if bot_id:
            query = query.filter(BotConfig.id == bot_id)

        bots = query.all()

        updated = 0
        skipped = 0
        throttled = 0

        for bot in bots:
            try:
                # ── Throttle check ──
                cfg = bot.ai_signal_config or {}
                last_refresh = cfg.get("_last_optimal_refresh_at")
                if last_refresh:
                    try:
                        last_dt = datetime.fromisoformat(last_refresh)
                        mins_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
                        if mins_since < _MIN_RECHECK_MINUTES:
                            throttled += 1
                            logger.debug(
                                f"[OPTIMAL CONFIG TASK] {bot.bot_name}: throttled "
                                f"({mins_since:.0f}m < {_MIN_RECHECK_MINUTES}m)"
                            )
                            continue
                    except Exception:
                        pass  # malformed timestamp, proceed anyway

                # ── Compute optimal config ──
                ticker = bot.symbol.upper().replace("/USDT:USDT", "USDT").replace("/USD:USD", "USD")
                optimal = _compute_optimal_config_sync(db, ticker)
                if not optimal:
                    skipped += 1
                    logger.info(
                        f"[OPTIMAL CONFIG TASK] {bot.bot_name}: no optimal config available for {ticker}"
                    )
                    continue

                # ── Compare with current config (ignore runtime state keys) ──
                current = dict(cfg)
                # Remove ephemeral keys for comparison
                for ephemeral_key in ("circuit_breaker_state", "config_history", "_last_optimal_refresh_at"):
                    current.pop(ephemeral_key, None)

                # Keys that define the "shape" of the config
                shape_keys = {
                    "min_score", "require_clear", "allowed_tiers", "allowed_statuses",
                    "sizing_multipliers", "circuit_breaker_thresholds", "portfolio_limits",
                }
                current_shape = {k: current.get(k) for k in shape_keys}
                optimal_shape = {k: optimal.get(k) for k in shape_keys}

                if current_shape == optimal_shape:
                    skipped += 1
                    logger.debug(
                        f"[OPTIMAL CONFIG TASK] {bot.bot_name}: config unchanged for {ticker}"
                    )
                    continue

                # ── Apply new config with merge ──
                merged = {**cfg, **optimal}
                merged["_last_optimal_refresh_at"] = datetime.now(timezone.utc).isoformat()

                # ── Historial de cambios ──
                history = merged.get("config_history", [])
                history.append({
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                    "reason": (
                        f"auto_recalibrate: ticker={ticker}, "
                        f"score≥{optimal.get('min_score')}, tiers={optimal.get('allowed_tiers')}, "
                        f"statuses={optimal.get('allowed_statuses')}"
                    ),
                    "config_snapshot": optimal,
                })
                # Mantener solo últimos 50
                merged["config_history"] = history[-50:]

                bot.ai_signal_config = merged
                updated += 1
                logger.info(
                    f"[OPTIMAL CONFIG TASK] {bot.bot_name}: refreshed config for {ticker} "
                    f"→ score≥{optimal.get('min_score')} tiers={optimal.get('allowed_tiers')} "
                    f"statuses={optimal.get('allowed_statuses')}"
                )

            except Exception as exc:
                logger.warning(
                    f"[OPTIMAL CONFIG TASK] {bot.bot_name}: failed to refresh config: {exc}"
                )
                skipped += 1

        db.commit()
        logger.info(
            f"[OPTIMAL CONFIG TASK] Completed: {updated} updated, {skipped} skipped, "
            f"{throttled} throttled, total {len(bots)} bots checked"
        )
        return {
            "updated": updated,
            "skipped": skipped,
            "throttled": throttled,
            "total": len(bots),
        }
