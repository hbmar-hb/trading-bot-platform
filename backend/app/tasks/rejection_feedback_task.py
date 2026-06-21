"""
Celery Beat task — auto-calibrates bot filters from rejection audit data.

Runs every 6 hours (after rejection_signal_audit_task has populated
would_have_been_winner). For each AI-enabled bot, reads audited rejections
for its ticker/timeframe and auto-adjusts filters if they are too aggressive
or too loose.

This closes the survival-bias feedback loop:
  rejections → audit → calibration → better thresholds → fewer false negatives
"""
from __future__ import annotations

from datetime import datetime, timezone

from celery import shared_task
from loguru import logger

from app.services.database import SessionLocal
from app.models.bot_config import BotConfig
def _to_compact_ticker(symbol: str) -> str:
    if not symbol:
        return symbol
    s = symbol.replace(".P", "").replace(".p", "")
    if "/" in s:
        base, rest = s.split("/", 1)
        quote = rest.split(":")[0] if ":" in rest else rest
        return base + quote
    return s


from app.services.rejection_feedback_optimizer import (
    compute_rejection_adjustments,
    apply_rejection_adjustments_to_config,
)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def calibrate_from_rejections(self):
    """Celery task — calibrate all AI bots from audited rejection data."""
    try:
        with SessionLocal() as db:
            bots = (
                db.query(BotConfig)
                .filter(
                    BotConfig.ai_signal_mode.is_(True),
                    BotConfig.status.in_(["active", "paused"]),
                )
                .all()
            )

            if not bots:
                logger.info("[REJECTION_FEEDBACK] No AI bots eligible for calibration.")
                return

            logger.info(f"[REJECTION_FEEDBACK] Calibrating {len(bots)} bot(s)...")

            adjusted_count = 0
            for bot in bots:
                try:
                    ticker = _to_compact_ticker(bot.symbol)
                    current_cfg = dict(bot.ai_signal_config or {})

                    adjustments = compute_rejection_adjustments(
                        db, ticker, bot, current_cfg, days=30
                    )

                    if adjustments:
                        new_cfg = apply_rejection_adjustments_to_config(
                            db, bot, current_cfg, adjustments
                        )
                        bot.ai_signal_config = new_cfg
                        db.commit()
                        adjusted_count += 1
                        logger.info(
                            f"[REJECTION_FEEDBACK] Calibrated bot '{bot.bot_name}' ({ticker}): "
                            f"{adjustments.get('_reasons', [])}"
                        )

                except Exception as bot_exc:
                    logger.warning(
                        f"[REJECTION_FEEDBACK] Failed to calibrate bot '{bot.bot_name}': {bot_exc}"
                    )
                    db.rollback()
                    continue

            logger.info(
                f"[REJECTION_FEEDBACK] Completed: {adjusted_count}/{len(bots)} bot(s) adjusted."
            )

    except Exception as exc:
        logger.error(f"[REJECTION_FEEDBACK] Task failed: {exc}")
        raise self.retry(exc=exc)
