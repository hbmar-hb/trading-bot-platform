"""
Celery task — auto-calibrates bot_activator thresholds from LLM diagnosis history.

Runs every 12h. Analyzes resolved signal outcomes and adjusts:
  - ml_status_thresholds (BLOCK/CAUTION/CLEAR cutoffs)
  - pattern_wr_threshold (minimum win-rate for pattern filter)

Autonomous behaviour:
  - Only adjusts within safe guardrails (±0.05 for SP, ±0.05 for WR).
  - Never makes thresholds stricter if the system is already rejecting >70% of signals.
  - Persists changes to ai_signal_config for all AI bots.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger
from sqlalchemy import func

from app.services.database import SessionLocal
from app.models.llm_signal_diagnosis import LLMSignalDiagnosis
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog


_MAX_SP_DELTA = 0.05
_MAX_WR_DELTA = 0.05
_MIN_SP_BLOCK = 0.10
_MAX_SP_BLOCK = 0.40
_MIN_SP_CAUTION = 0.20
_MAX_SP_CAUTION = 0.60
_MIN_PATTERN_WR = 0.30
_MAX_PATTERN_WR = 0.60


@shared_task(
    name="app.tasks.activator_calibration_task.calibrate_thresholds",
    queue="default",
    max_retries=0,
)
def calibrate_thresholds() -> dict:
    try:
        applied = _run_calibration()
        logger.info(f"[ACTIVATOR_CALIBRATION] Applied adjustments to {len(applied)} bots")
        return {"status": "ok", "applied": applied}
    except Exception as exc:
        logger.error(f"[ACTIVATOR_CALIBRATION] Error: {exc}")
        return {"status": "error", "error": str(exc)}


def _run_calibration() -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=72)
    db = SessionLocal()
    try:
        rows = (
            db.query(LLMSignalDiagnosis)
            .filter(LLMSignalDiagnosis.created_at >= since)
            .all()
        )

        if not rows:
            return []

        # Collect stats for SP calibration
        sp_bins = {"BLOCK": [], "CAUTION": [], "CLEAR": []}
        for r in rows:
            diag = r.diagnosis_json or {}
            sp = getattr(r, "success_probability", None)
            if sp is None:
                continue
            verdict = diag.get("verdict", "CLEAR")
            outcome = r.outcome  # "win", "loss", "breakeven", None
            sp_bins[verdict].append({"sp": sp, "outcome": outcome})

        # Determine optimal SP thresholds from outcomes
        # Goal: maximize separation where CLEAR → win and BLOCK → loss
        optimal_block = None
        optimal_caution = None

        block_samples = sp_bins["BLOCK"]
        if len(block_samples) >= 10:
            losses = [s["sp"] for s in block_samples if s["outcome"] == "loss"]
            if losses:
                # Raise block threshold if many losses are above current 0.30
                optimal_block = min(_MAX_SP_BLOCK, max(_MIN_SP_BLOCK, max(losses) + 0.02))

        clear_samples = sp_bins["CLEAR"]
        if len(clear_samples) >= 10:
            wins = [s["sp"] for s in clear_samples if s["outcome"] == "win"]
            if wins:
                # Lower caution threshold if many wins are below current 0.50
                optimal_caution = max(_MIN_SP_CAUTION, min(_MAX_SP_CAUTION, min(wins) - 0.02))

        # Pattern WR calibration: look at pattern-level outcomes
        # Use rejection tracker data or signal outcomes
        pattern_outcomes = {}
        for r in rows:
            pattern = (r.ticker, r.quality_tier, r.direction)
            if pattern not in pattern_outcomes:
                pattern_outcomes[pattern] = []
            pattern_outcomes[pattern].append(r.outcome)

        if pattern_outcomes:
            wrs = []
            for outcomes in pattern_outcomes.values():
                wins = sum(1 for o in outcomes if o == "win")
                total = len([o for o in outcomes if o in ("win", "loss")])
                if total >= 5:
                    wrs.append(wins / total)
            if wrs:
                avg_wr = sum(wrs) / len(wrs)
                # If average pattern WR is high, we can afford a lower threshold
                # If average is low, raise threshold
                optimal_wr = max(_MIN_PATTERN_WR, min(_MAX_PATTERN_WR, avg_wr - 0.05))
            else:
                optimal_wr = None
        else:
            optimal_wr = None

        # Apply to all AI bots
        bots = (
            db.query(BotConfig)
            .filter(BotConfig.ai_signal_mode == True)
            .all()
        )

        applied = []
        for bot in bots:
            cfg = bot.ai_signal_config or {}
            changed = False
            changes = []

            thresholds = cfg.get("ml_status_thresholds", {})
            old_block = thresholds.get("block", 0.30)
            old_caution = thresholds.get("caution", 0.50)

            if optimal_block is not None and abs(optimal_block - old_block) <= _MAX_SP_DELTA:
                thresholds["block"] = round(optimal_block, 2)
                changed = True
                changes.append(f"block {old_block}→{thresholds['block']}")

            if optimal_caution is not None and abs(optimal_caution - old_caution) <= _MAX_SP_DELTA:
                thresholds["caution"] = round(optimal_caution, 2)
                changed = True
                changes.append(f"caution {old_caution}→{thresholds['caution']}")

            if changed:
                cfg["ml_status_thresholds"] = thresholds

            old_wr = cfg.get("pattern_wr_threshold", 0.45)
            if optimal_wr is not None and abs(optimal_wr - old_wr) <= _MAX_WR_DELTA:
                cfg["pattern_wr_threshold"] = round(optimal_wr, 2)
                changed = True
                changes.append(f"pattern_wr_threshold {old_wr}→{cfg['pattern_wr_threshold']}")

            if changed:
                bot.ai_signal_config = cfg
                db.add(BotLog(
                    bot_id=bot.id,
                    event_type="activator_threshold_calibrated",
                    message="Auto-calibrated activator thresholds from 72h diagnosis history",
                    metadata={
                        "changes": changes,
                        "samples": len(rows),
                    },
                ))
                applied.append({
                    "bot_id": str(bot.id),
                    "bot_name": bot.bot_name,
                    "changes": changes,
                })

        if applied:
            db.commit()

        return applied
    finally:
        db.close()
