"""
Threshold Optimizer — calibra thresholds de gates basado en trades históricos.

Para cada gate, analiza:
- Cuántos trades ganadores bloqueó (false negative)
- Cuántos trades perdedores dejó pasar (false positive)
- Ajuste sugerido al threshold

Gates calibrables:
- Session/Funding
- OI/CVD
- Rolling Beta
- Slippage
- Dynamic Horizon
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# ── Calibration constants ──────────────────────────────────
MIN_TRADES_FOR_CALIBRATION = 30
WIN_RATE_TARGET = Decimal("0.55")


def _win_rate(trades: list) -> Decimal | None:
    if not trades:
        return None
    wins = sum(1 for t in trades if t > 0)
    return Decimal(wins) / Decimal(len(trades))


def calibrate_gate_thresholds(db: Session, days: int = 60) -> dict:
    """
    Analyzes historical trades and suggests threshold adjustments.
    Returns dict with current vs suggested thresholds per gate.
    """
    from app.models.position import Position
    from app.models.bot_config import BotConfig
    from sqlalchemy import select, and_

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    positions = db.execute(
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            and_(
                BotConfig.paper_balance_id.is_(None),
                Position.status == "closed",
                Position.source == "ai_bot",
                Position.closed_at >= cutoff,
                Position.extra_config.isnot(None),
            )
        )
    ).scalars().all()

    if len(positions) < MIN_TRADES_FOR_CALIBRATION:
        return {"status": "insufficient_data", "trades": len(positions), "required": MIN_TRADES_FOR_CALIBRATION}

    results = {}

    # ── Session/Funding gate ──
    sf_blocked = [p for p in positions if p.extra_config.get("session_funding", {}).get("blocked")]
    sf_caution = [p for p in positions if p.extra_config.get("session_funding", {}).get("caution")]
    sf_passed = [p for p in positions if not p.extra_config.get("session_funding", {}).get("blocked")]

    if sf_blocked:
        sf_blocked_wr = _win_rate([float(p.realized_pnl or 0) for p in sf_blocked])
        sf_passed_wr = _win_rate([float(p.realized_pnl or 0) for p in sf_passed])
        results["session_funding"] = {
            "blocked_count": len(sf_blocked),
            "blocked_win_rate": round(float(sf_blocked_wr * 100), 1) if sf_blocked_wr else None,
            "passed_win_rate": round(float(sf_passed_wr * 100), 1) if sf_passed_wr else None,
            "suggestion": (
                "Consider raising funding threshold — blocked trades had high WR"
                if sf_blocked_wr and sf_blocked_wr > (sf_passed_wr or Decimal("0"))
                else "Threshold seems appropriate"
            ),
        }

    # ── OI/CVD gate ──
    oi_blocked = [p for p in positions if p.extra_config.get("oi_cvd", {}).get("blocked")]
    oi_passed = [p for p in positions if not p.extra_config.get("oi_cvd", {}).get("blocked")]

    if oi_blocked:
        oi_blocked_wr = _win_rate([float(p.realized_pnl or 0) for p in oi_blocked])
        oi_passed_wr = _win_rate([float(p.realized_pnl or 0) for p in oi_passed])
        results["oi_cvd"] = {
            "blocked_count": len(oi_blocked),
            "blocked_win_rate": round(float(oi_blocked_wr * 100), 1) if oi_blocked_wr else None,
            "passed_win_rate": round(float(oi_passed_wr * 100), 1) if oi_passed_wr else None,
            "suggestion": (
                "Consider raising OI ROC threshold — blocked trades had high WR"
                if oi_blocked_wr and oi_blocked_wr > (oi_passed_wr or Decimal("0"))
                else "Threshold seems appropriate"
            ),
        }

    # ── Rolling Beta gate ──
    beta_blocked = [p for p in positions if p.extra_config.get("rolling_beta", {}).get("blocked")]
    beta_passed = [p for p in positions if not p.extra_config.get("rolling_beta", {}).get("blocked")]

    if beta_blocked:
        beta_blocked_wr = _win_rate([float(p.realized_pnl or 0) for p in beta_blocked])
        beta_passed_wr = _win_rate([float(p.realized_pnl or 0) for p in beta_passed])
        results["rolling_beta"] = {
            "blocked_count": len(beta_blocked),
            "blocked_win_rate": round(float(beta_blocked_wr * 100), 1) if beta_blocked_wr else None,
            "passed_win_rate": round(float(beta_passed_wr * 100), 1) if beta_passed_wr else None,
            "suggestion": (
                "Consider raising beta threshold — blocked trades had high WR"
                if beta_blocked_wr and beta_blocked_wr > (beta_passed_wr or Decimal("0"))
                else "Threshold seems appropriate"
            ),
        }

    # ── Slippage gate ──
    slip_aborted = [p for p in positions if p.extra_config.get("slippage_aborted")]
    slip_passed = [p for p in positions if not p.extra_config.get("slippage_aborted")]

    if slip_aborted:
        slip_aborted_wr = _win_rate([float(p.realized_pnl or 0) for p in slip_aborted])
        slip_passed_wr = _win_rate([float(p.realized_pnl or 0) for p in slip_passed])
        results["slippage"] = {
            "aborted_count": len(slip_aborted),
            "aborted_win_rate": round(float(slip_aborted_wr * 100), 1) if slip_aborted_wr else None,
            "passed_win_rate": round(float(slip_passed_wr * 100), 1) if slip_passed_wr else None,
            "suggestion": (
                "Consider raising slippage threshold — aborted trades had high WR"
                if slip_aborted_wr and slip_aborted_wr > (slip_passed_wr or Decimal("0"))
                else "Threshold seems appropriate"
            ),
        }

    # ── Dynamic Horizon ──
    dh_applied = [p for p in positions if p.extra_config.get("dynamic_horizon", {}).get("applied")]
    dh_not_applied = [p for p in positions if not p.extra_config.get("dynamic_horizon", {}).get("applied")]

    if dh_applied:
        dh_applied_wr = _win_rate([float(p.realized_pnl or 0) for p in dh_applied])
        dh_not_wr = _win_rate([float(p.realized_pnl or 0) for p in dh_not_applied])
        results["dynamic_horizon"] = {
            "applied_count": len(dh_applied),
            "applied_win_rate": round(float(dh_applied_wr * 100), 1) if dh_applied_wr else None,
            "not_applied_win_rate": round(float(dh_not_wr * 100), 1) if dh_not_wr else None,
            "suggestion": (
                "Dynamic horizon is helping — keep it enabled"
                if dh_applied_wr and dh_not_wr and dh_applied_wr > dh_not_wr
                else "Dynamic horizon may need tuning"
            ),
        }

    # ── Overall ──
    all_pnls = [float(p.realized_pnl or 0) for p in positions]
    overall_wr = _win_rate(all_pnls)

    return {
        "status": "ok",
        "trades_analyzed": len(positions),
        "period_days": days,
        "overall_win_rate": round(float(overall_wr * 100), 1) if overall_wr else None,
        "overall_expectancy": round(sum(all_pnls) / len(all_pnls), 4) if all_pnls else None,
        "gates": results,
    }


# ── Model Threshold Optimizer (Evaluación 1) ─────────────────────────────────

_MIN_TRADES_PER_CELL = 20
_SCORE_THRESHOLDS = [60, 70, 75, 80, 85]
_PROB_THRESHOLDS = [0.5, 0.6, 0.7, 0.75, 0.8]


def optimize_model_thresholds(validation_data: list[dict]) -> dict | None:
    """Optimize score + probability thresholds using walk-forward validation data.

    Evaluación 1: Optimize ONLY during retrain, not rolling weekly.
    Use the ENTIRE walk-forward validation set, not just last 30 days.

    Args:
        validation_data: List of dicts with keys:
            score, success_probability, outcome (SUCCESS/FAILURE), pnl_pct

    Returns:
        Dict with best thresholds or None if insufficient data.
    """
    import math

    if len(validation_data) < _MIN_TRADES_PER_CELL:
        return {"status": "insufficient_data", "trades": len(validation_data), "required": _MIN_TRADES_PER_CELL}

    results = []

    for score_t in _SCORE_THRESHOLDS:
        for prob_t in _PROB_THRESHOLDS:
            filtered = [
                t for t in validation_data
                if t.get("score", 0) >= score_t
                and (t.get("success_probability") is None or t.get("success_probability", 0.0) >= (1.0 - prob_t))
            ]

            if len(filtered) < _MIN_TRADES_PER_CELL:
                continue

            metrics = _calculate_metrics(filtered)
            results.append({
                "score_threshold": score_t,
                "prob_threshold": prob_t,
                "sharpe": metrics["sharpe"],
                "win_rate": metrics["win_rate"],
                "expectancy": metrics["expectancy"],
                "n_trades": len(filtered),
            })

    valid = [r for r in results if r["n_trades"] >= _MIN_TRADES_PER_CELL]
    if not valid:
        return {"status": "no_valid_combinations", "trades": len(validation_data)}

    # Select maximum Sharpe with at least MIN_TRADES_PER_CELL trades
    best = max(valid, key=lambda x: x["sharpe"])

    return {
        "status": "ok",
        "score_threshold": best["score_threshold"],
        "prob_threshold": best["prob_threshold"],
        "expected_sharpe": round(best["sharpe"], 3),
        "expected_win_rate": round(best["win_rate"], 3),
        "expected_expectancy": round(best["expectancy"], 4),
        "n_trades": best["n_trades"],
        "combinations_tested": len(results),
    }


def _calculate_metrics(trades: list[dict]) -> dict:
    """Calculate Sharpe, win rate, and expectancy from filtered trades."""
    returns = [float(t.get("pnl_pct", 0) or 0) for t in trades]
    n = len(returns)
    if n < 2:
        return {"sharpe": 0.0, "win_rate": 0.0, "expectancy": 0.0}

    wins = [r for r in returns if r > 0]
    win_rate = len(wins) / n
    expectancy = sum(returns) / n

    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / n
    std_r = math.sqrt(variance) if variance > 0 else 0.0
    sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

    return {
        "sharpe": round(sharpe, 3),
        "win_rate": round(win_rate, 3),
        "expectancy": round(expectancy, 4),
    }
