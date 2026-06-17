"""
Celery task — analyze LLM diagnoses and AUTO-APPLY threshold adjustments.

Runs every 24h. Looks at diagnoses from the last 72h and detects gates
where Kimi consistently disagrees with the bot activator (i.e. Kimi says
CLEAR but the gate blocked the signal).

Autonomous behaviour:
  - Automatically applies safe adjustments to ai_signal_config with guardrails.
  - Logs every change to BotLog for audit trail.
  - Never removes safety tiers (STRONG, CLEAR); only adds weaker ones if stats support it.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from celery import shared_task
from loguru import logger
from sqlalchemy import func, select

from app.services.database import SessionLocal
from app.models.llm_signal_diagnosis import LLMSignalDiagnosis
from app.models.bot_config import BotConfig
from app.models.bot_log import BotLog


# Guardrails for auto-application
_MAX_MIN_SCORE_DELTA = 10
_MIN_MIN_SCORE = 20
_MAX_MIN_SCORE = 95
_MAX_CONCURRENT_DELTA = 2
_MIN_CONCURRENT = 1
_MAX_CONCURRENT = 10
_MAX_SP_THRESHOLD_DELTA = 0.05


@shared_task(
    name="app.tasks.llm_threshold_optimizer.analyze_and_apply",
    queue="default",
    max_retries=0,
)
def analyze_and_apply() -> dict:
    try:
        applied = _build_and_apply_recommendations()
        logger.info(f"[LLM_THRESHOLD_OPT] Applied {len(applied)} adjustments")
        return {"status": "ok", "applied": applied}
    except Exception as exc:
        logger.error(f"[LLM_THRESHOLD_OPT] Error: {exc}")
        return {"status": "error", "error": str(exc)}


def _build_recommendations() -> list[dict]:
    """Build threshold recommendations without applying them."""
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

        by_trigger: dict[str, list[dict]] = {}
        for r in rows:
            source = r.trigger_source
            if source not in by_trigger:
                by_trigger[source] = []
            diag = r.diagnosis_json or {}
            by_trigger[source].append({
                "verdict": diag.get("verdict", "CLEAR"),
                "confidence": diag.get("confidence", 50),
                "outcome": r.outcome,
            })

        recommendations = []
        for source, diags in by_trigger.items():
            total = len(diags)
            if total < 5:
                continue
            clear_but_blocked = [d for d in diags if d["verdict"] == "CLEAR"]
            fp_rate = len(clear_but_blocked) / total if total else 0
            if fp_rate < 0.30:
                continue
            recommendations.append({
                "gate": source,
                "diags": diags,
                "fp_rate": fp_rate,
                "sample_size": total,
                "clear_but_blocked": len(clear_but_blocked),
            })
        return recommendations
    finally:
        db.close()


def get_threshold_recommendations() -> list[dict]:
    """Public-safe wrapper that returns recommendations without applying them."""
    recs = _build_recommendations()
    return [
        {
            "gate": r["gate"],
            "false_positive_rate": r["fp_rate"],
            "sample_size": r["sample_size"],
            "clear_but_blocked": r["clear_but_blocked"],
        }
        for r in recs
    ]


def _build_and_apply_recommendations() -> list[dict]:
    recommendations = _build_recommendations()
    if not recommendations:
        return []

    db = SessionLocal()
    try:
        applied_changes = []
        for rec in recommendations:
            change = _apply_gate_adjustment(db, rec["gate"], rec["diags"], rec["fp_rate"])
            if change:
                applied_changes.append(change)
        return applied_changes
    finally:
        db.close()


def _apply_gate_adjustment(db, source: str, diags: list[dict], fp_rate: float) -> dict | None:
    """Apply a single gate adjustment across all bots with guardrails."""
    total = len(diags)
    clear_but_blocked = [d for d in diags if d["verdict"] == "CLEAR"]
    avg_conf = sum(d["confidence"] for d in clear_but_blocked) / len(clear_but_blocked) if clear_but_blocked else 50

    # Fetch bots that are candidates for adjustment (AI mode, active or paused by system)
    bots = (
        db.query(BotConfig)
        .filter(BotConfig.ai_signal_mode == True)
        .all()
    )

    if not bots:
        return None

    changes_made = []

    for bot in bots:
        cfg = bot.ai_signal_config or {}
        old_cfg = dict(cfg)
        changed = False

        if source == "anti_fake":
            thresholds = cfg.get("ml_status_thresholds", {})
            block_thr = thresholds.get("block", 0.30)
            caution_thr = thresholds.get("caution", 0.50)

            # Slightly relax if FP rate is high
            new_block = max(0.10, round(block_thr - 0.05, 2))
            new_caution = max(new_block + 0.05, round(caution_thr - 0.05, 2))

            if new_block != block_thr or new_caution != caution_thr:
                thresholds["block"] = new_block
                thresholds["caution"] = new_caution
                cfg["ml_status_thresholds"] = thresholds
                changed = True
                changes_made.append(f"ml_status_thresholds: block {block_thr}→{new_block}, caution {caution_thr}→{new_caution}")

        elif source == "gate_score":
            old_min = cfg.get("min_score", 60)
            new_min = max(_MIN_MIN_SCORE, min(_MAX_MIN_SCORE, old_min - 5))
            if new_min != old_min:
                cfg["min_score"] = new_min
                changed = True
                changes_made.append(f"min_score: {old_min}→{new_min}")

        elif source == "gate_concurrent":
            old_max = cfg.get("max_concurrent", 1)
            new_max = min(_MAX_CONCURRENT, old_max + 1)
            if new_max != old_max:
                cfg["max_concurrent"] = new_max
                changed = True
                changes_made.append(f"max_concurrent: {old_max}→{new_max}")

        elif source == "gate_tier":
            old_tiers = cfg.get("allowed_tiers", ["STRONG"])
            if "MODERATE" not in old_tiers:
                new_tiers = old_tiers + ["MODERATE"]
                cfg["allowed_tiers"] = new_tiers
                changed = True
                changes_made.append(f"allowed_tiers: added MODERATE")

        if changed:
            bot.ai_signal_config = cfg
            db.add(BotLog(
                bot_id=bot.id,
                event_type="auto_threshold_adjustment",
                message=f"Auto-adjusted {source} based on LLM diagnosis feedback (FP={fp_rate:.0%})",
                metadata={
                    "gate": source,
                    "false_positive_rate": round(fp_rate, 2),
                    "avg_confidence": round(avg_conf, 1),
                    "changes": changes_made,
                    "old_config": old_cfg,
                    "new_config": cfg,
                },
            ))

    if changes_made:
        db.commit()
        return {
            "gate": source,
            "bots_affected": len(bots),
            "false_positive_rate": round(fp_rate, 2),
            "changes": changes_made,
        }

    return None
