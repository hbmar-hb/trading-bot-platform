"""
Celery task: Deployment Gate evaluation.

Runs every 1 hour and evaluates unified system health.
Also evaluates per-symbol/timeframe health so one bad pair
does not poison the entire fleet.
"""
from celery import shared_task
from loguru import logger
from sqlalchemy import select

from app.services.database import SessionLocal
from app.services.deployment_gate import (
    evaluate_deployment_gate,
    evaluate_symbol_deployment_gate_regime_aware,
    _proactively_manage_symbol_gates,
)
from app.models.bot_config import BotConfig


@shared_task(name="app.tasks.deployment_gate_task.evaluate_deployment_gate_task")
def evaluate_deployment_gate_task() -> dict:
    """Task: evaluate unified deployment gate + per-symbol/TF gates."""
    db = SessionLocal()
    try:
        # 1. Global gate (unchanged)
        log = evaluate_deployment_gate(db)
        logger.info(
            f"[DeploymentGate] State={log.state} sizing={float(log.sizing_multiplier)} "
            f"reasons={log.reasons}"
        )

        # 2. Per-symbol/TF gates
        active_pairs = db.execute(
            select(BotConfig.symbol, BotConfig.timeframe)
            .where(
                BotConfig.ai_signal_mode == True,
                BotConfig.status == "active",
                BotConfig.paper_balance_id.is_(None),
            )
            .distinct()
        ).all()

        sym_evaluated = 0
        for sym, tf in active_pairs:
            try:
                evaluate_symbol_deployment_gate_regime_aware(db, sym, tf)
                sym_evaluated += 1
            except Exception:
                logger.exception(f"[SYM GATE] Failed for {sym}/{tf}")

        # 3. Apply per-symbol proactive blocks/unblocks
        _proactively_manage_symbol_gates(db)

        logger.info(
            f"[DeploymentGate] Evaluated {sym_evaluated} symbol/timeframe pairs"
        )

        return {
            "state": log.state,
            "sizing_multiplier": float(log.sizing_multiplier),
            "reasons": log.reasons,
            "symbol_pairs_evaluated": sym_evaluated,
        }
    except Exception as exc:
        logger.error(f"[DeploymentGate] Error: {exc}")
        raise
    finally:
        db.close()
