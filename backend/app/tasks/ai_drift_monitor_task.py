"""Celery task: periodic feature drift monitoring.

Runs every 4 hours to check for feature drift across all active ticker/timeframe pairs.
Autonomous behaviour:
  - DEGRADED  → reduces sizing multiplier to 0.5
  - CRITICAL/PAUSED → pauses bot, marks system_paused_by=drift
  - HEALTHY   → restores sizing / resumes bot if it was paused by drift
"""
from __future__ import annotations

from datetime import datetime, timezone

from celery import shared_task
from loguru import logger

from app.services.database import SessionLocal
from app.services.drift_detector import check_feature_drift, build_reference_distribution
from app.services.autonomy_state import mark_paused, clear_pause
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog


@shared_task(bind=True, max_retries=2)
def monitor_feature_drift(self) -> dict:
    """Check feature drift for all active AI signal ticker/timeframe pairs."""
    db = SessionLocal()
    try:
        # Find all unique ticker/timeframe pairs from active bots with AI signals
        active_bots = (
            db.query(BotConfig)
            .filter(
                BotConfig.ai_signal_mode == True,
                BotConfig.status == "active",
            )
            .all()
        )

        # Deduplicate by ticker/timeframe
        pairs = set()
        for bot in active_bots:
            tf = "1h"
            if bot.ai_signal_config and "timeframe" in bot.ai_signal_config:
                tf = bot.ai_signal_config["timeframe"]
            ticker = bot.symbol.upper().replace("/", "").replace(":USDT", "")
            pairs.add((ticker, tf, str(bot.id)))

        if not pairs:
            logger.info("[DRIFT_TASK] No active AI bots found, skipping drift check")
            return {"checked": 0, "status": "no_bots"}

        results = []
        for ticker, timeframe, bot_id in pairs:
            model_id = f"xgb_{ticker}_{timeframe}"

            try:
                report = check_feature_drift(db, ticker, timeframe, model_id)
                bot = db.query(BotConfig).filter(BotConfig.id == bot_id).first()

                if report.overall_status in ("DEGRADED", "PAUSED", "CRITICAL"):
                    db.add(BotLog(
                        bot_id=bot_id,
                        event_type="drift_detected",
                        message=f"Feature drift {report.overall_status} for {ticker}/{timeframe}",
                        metadata={
                            "ticker": ticker,
                            "timeframe": timeframe,
                            "model_id": model_id,
                            "status": report.overall_status,
                            "max_psi": report.max_psi,
                            "action": report.action,
                            "features": report.features,
                        },
                    ))
                    db.commit()

                # ── AUTONOMOUS ACTIONS ──
                if bot:
                    cfg = bot.ai_signal_config or {}
                    autonomy = cfg.get("autonomy_state", {})

                    if report.overall_status == "CRITICAL":
                        if mark_paused(autonomy, "drift"):
                            cfg["execution_blocked"] = True
                            cfg["execution_blocked_reason"] = "drift"
                            cfg["autonomy_state"] = autonomy
                            bot.ai_signal_config = cfg
                            logger.critical(
                                f"[DRIFT_TASK] Auto-blocked bot {bot.bot_name} — "
                                f"drift CRITICAL (psi={report.max_psi:.3f})"
                            )

                    elif report.overall_status == "DEGRADED":
                        old_sizing = cfg.get("sizing_multiplier", 1.0)
                        if old_sizing > 0.5:
                            cfg["sizing_multiplier"] = 0.5
                            bot.ai_signal_config = cfg
                            logger.warning(
                                f"[DRIFT_TASK] Auto-reduced sizing for bot {bot.bot_name} "
                                f"to 50% — drift DEGRADED (psi={report.max_psi:.3f})"
                            )

                    elif report.overall_status == "HEALTHY":
                        # Unblock if previously blocked by drift
                        if clear_pause(autonomy, "drift"):
                            cfg.pop("execution_blocked", None)
                            cfg.pop("execution_blocked_reason", None)
                            cfg["autonomy_state"] = autonomy
                            bot.ai_signal_config = cfg
                            logger.info(
                                f"[DRIFT_TASK] Auto-unblocked bot {bot.bot_name} — drift HEALTHY"
                            )

                    db.commit()

                results.append({
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "status": report.overall_status,
                    "max_psi": report.max_psi,
                    "action": report.action,
                })

            except Exception as exc:
                logger.error(f"[DRIFT_TASK] Failed checking {ticker}/{timeframe}: {exc}")
                results.append({
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "status": "ERROR",
                    "error": str(exc),
                })

        # Summary
        degraded = sum(1 for r in results if r["status"] == "DEGRADED")
        paused = sum(1 for r in results if r["status"] in ("PAUSED", "CRITICAL"))
        healthy = sum(1 for r in results if r["status"] == "HEALTHY")

        # ── GLOBAL SANITY CHECK ──
        # If >3 tickers have PSI > 1.0, trigger a temporary global pause
        high_drift_count = sum(1 for r in results if r.get("max_psi", 0) > 1.0)
        if high_drift_count > 3:
            logger.critical(
                f"[DRIFT_TASK] GLOBAL PAUSE triggered — {high_drift_count} tickers "
                f"have PSI > 1.0. Pausing all AI bots for 30 min."
            )
            for bot in active_bots:
                cfg = bot.ai_signal_config or {}
                autonomy = cfg.get("autonomy_state", {})
                if mark_paused(autonomy, "drift_global"):
                    cfg["execution_blocked"] = True
                    cfg["execution_blocked_reason"] = "drift_global"
                    cfg["autonomy_state"] = autonomy
                    # Reset inflated drift multiplier back to 1.0
                    if cfg.get("drift_psi_multiplier", 1.0) > 1.0:
                        cfg["drift_psi_multiplier"] = 1.0
                        logger.warning(
                            f"[DRIFT_TASK] Reset drift_psi_multiplier to 1.0 for {bot.bot_name}"
                        )
                    bot.ai_signal_config = cfg
            db.commit()

        logger.info(
            f"[DRIFT_TASK] Checked {len(results)} pairs: "
            f"healthy={healthy} degraded={degraded} paused={paused} high_drift={high_drift_count}"
        )

        # Health-check hook: record last successful run timestamp
        try:
            from app.services.cache import sync_redis
            sync_redis.setex(
                "drift_monitor:last_run",
                int(timedelta(days=2).total_seconds()),
                datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            pass

        return {
            "checked": len(results),
            "healthy": healthy,
            "degraded": degraded,
            "paused": paused,
            "high_drift_count": high_drift_count,
            "results": results,
        }

    except Exception as exc:
        logger.error(f"[DRIFT_TASK] Drift monitor failed: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=300)
    finally:
        db.close()


@shared_task
def rebuild_drift_references() -> dict:
    """Rebuild reference distributions for all active pairs.

    Should be called after model retraining to update baselines.
    """
    db = SessionLocal()
    try:
        active_bots = (
            db.query(BotConfig)
            .filter(
                BotConfig.ai_signal_mode == True,
                BotConfig.status == "active",
            )
            .all()
        )

        pairs = set()
        for bot in active_bots:
            tf = "1h"
            if bot.ai_signal_config and "timeframe" in bot.ai_signal_config:
                tf = bot.ai_signal_config["timeframe"]
            ticker = bot.symbol.upper().replace("/", "").replace(":USDT", "")
            pairs.add((ticker, tf))

        rebuilt = []
        for ticker, timeframe in pairs:
            model_id = f"xgb_{ticker}_{timeframe}"
            try:
                ref = build_reference_distribution(db, ticker, timeframe, model_id)
                rebuilt.append({
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "status": "built" if "error" not in ref else "failed",
                    "features": len(ref.get("features", {})),
                })
            except Exception as exc:
                rebuilt.append({
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "status": "error",
                    "error": str(exc),
                })

        return {"rebuilt": len(rebuilt), "details": rebuilt}
    finally:
        db.close()
