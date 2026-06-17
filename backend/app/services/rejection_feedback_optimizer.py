"""
Rejection Feedback Optimizer — auto-calibrates bot filter thresholds
based on audited rejection data (survival-bias feedback loop).

When a filter rejects signals that would have been winners,
the system automatically loosens that filter.
When a filter lets through signals that would have lost,
the system tightens it.

All changes are rate-limited and bounded for safety.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select, func

from app.models.ai_signal_rejected import AISignalRejected
from app.models.position import Position


# ─── Calibration Rules ───────────────────────────────────────────────────────

_RULES = {
    "tier": {"loosen_would_win_pct": 60, "tighten_would_win_pct": 30, "min_audited": 10},
    "score": {"loosen_would_win_pct": 55, "tighten_would_win_pct": 30, "min_audited": 10},
    "concurrent": {"loosen_would_win_pct": 50, "tighten_would_win_pct": 30, "min_audited": 10},
    "portfolio": {"loosen_would_win_pct": 55, "tighten_would_win_pct": 30, "min_audited": 10},
    "status": {"loosen_would_win_pct": 60, "tighten_would_win_pct": 30, "min_audited": 10},
    "drift": {"loosen_would_win_pct": 55, "tighten_would_win_pct": 30, "min_audited": 10},
    "kelly": {"loosen_would_win_pct": 55, "tighten_would_win_pct": 30, "min_audited": 10},
    "rolling_beta": {"loosen_would_win_pct": 55, "tighten_would_win_pct": 30, "min_audited": 10},
    "slippage": {"loosen_would_win_pct": 55, "tighten_would_win_pct": 30, "min_audited": 10},
}

_HARD_BOUNDS = {
    "min_score": (20, 95),
    "max_concurrent": (1, 10),
    "max_total_exposure_pct": (20.0, 80.0),
    "max_symbol_exposure_pct": (15.0, 60.0),
    "max_directional_exposure_pct": (20.0, 70.0),
    "drift_psi_multiplier": (0.5, 1.20),
    "kelly_edge_multiplier": (0.3, 2.0),
    "rolling_beta_threshold_multiplier": (0.5, 2.0),
    "slippage_abort_ratio_multiplier": (0.5, 2.0),
}

_RATE_LIMITS = {
    "min_score_24h": (-20, 10),          # allow faster loosening
    "max_concurrent_24h": (-3, 2),       # max ±3 per 24h
    "portfolio_48h": (0.60, 1.30),       # wider range
    "tier_12h": 2,                        # max 2 tier levels per 12h
    "status_12h": 2,                      # max 2 status levels per 12h
    "drift_psi_48h": (0.70, 1.15),
    "kelly_edge_48h": (0.70, 1.30),
    "rolling_beta_48h": (0.70, 1.30),
    "slippage_abort_48h": (0.70, 1.30),
    "min_cycle_hours": 2,                 # react faster (2h minimum)
}

_TIER_ORDER = ["STRONG", "MODERATE", "WEAK"]
_STATUS_ORDER = ["CLEAR", "CAUTION", "BLOCK"]


def _get_rejection_summary(db, ticker: str, days: int = 30) -> dict[str, dict]:
    """Fetch audited rejection stats by reason for a ticker."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    from sqlalchemy import case

    rows = (
        db.query(
            AISignalRejected.rejection_reason,
            func.count().label("count"),
            func.sum(
                case((AISignalRejected.would_have_been_winner.is_(True), 1), else_=0)
            ).label("wins"),
            func.sum(
                case((AISignalRejected.would_have_been_winner.isnot(None), 1), else_=0)
            ).label("audited"),
        )
        .filter(
            AISignalRejected.ticker == ticker,
            AISignalRejected.rejected_at >= since,
        )
        .group_by(AISignalRejected.rejection_reason)
        .all()
    )

    result = {}
    for reason, count, wins, audited in rows:
        win_pct = round(wins / audited * 100, 1) if audited and audited > 0 else None
        result[reason] = {"count": count, "wins": wins, "audited": audited, "would_win_pct": win_pct}
    return result


def _has_open_positions_with_negative_pnl(db, bot) -> bool:
    """Check if bot has open positions with negative unrealized PnL."""
    from sqlalchemy import select

    stmt = select(func.avg(Position.unrealized_pnl)).where(
        Position.bot_id == str(bot.id),
        Position.status == "open",
    )
    result = db.execute(stmt)
    avg_pnl = result.scalar()
    return avg_pnl is not None and float(avg_pnl) < 0


def _get_meta(current_cfg: dict) -> dict:
    """Get or initialize rejection calibration meta."""
    return current_cfg.get("rejection_calibration_meta", {})


def _is_rate_limited(meta: dict, now: datetime) -> bool:
    """Check if minimum cycle time has passed."""
    last = meta.get("last_calibration_at")
    if not last:
        return False
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    hours_since = (now - last).total_seconds() / 3600
    return hours_since < _RATE_LIMITS["min_cycle_hours"]


def _window_delta(meta: dict, now: datetime, key: str, window_hours: int) -> float:
    """Sum of deltas applied within the last N hours."""
    history = meta.get("history", [])
    cutoff = now - timedelta(hours=window_hours)
    total = 0.0
    for entry in history:
        ts = entry.get("at")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts and ts >= cutoff:
            total += entry.get(key, 0)
    return total


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_rejection_adjustments(
    db,
    ticker: str,
    bot,
    current_cfg: dict,
    days: int = 30,
) -> dict[str, Any]:
    """
    Compute filter adjustments from audited rejection data.
    Returns dict of proposed changes (may be empty if no action needed).
    """
    now = datetime.now(timezone.utc)
    meta = _get_meta(current_cfg)

    if _is_rate_limited(meta, now):
        return {}

    summary = _get_rejection_summary(db, ticker, days=days)
    if not summary:
        return {}

    adjustments: dict[str, Any] = {}
    reasons: list[str] = []

    # Helper for proportional adjustment magnitude
    def _damage_delta(win_pct: float, base: float, loosen_thr: float, tighten_thr: float) -> float:
        """Return proportional adjustment based on how far win_pct is from thresholds."""
        if win_pct is None:
            return 0.0
        if win_pct > loosen_thr:
            # More damage → bigger loosening
            return -base * ((win_pct - loosen_thr) / 20.0 + 1.0)
        elif win_pct < tighten_thr:
            return base * ((tighten_thr - win_pct) / 20.0 + 1.0)
        return 0.0

    # ─── TIER filter ─────────────────────────────────────────────────────────
    tier_data = summary.get("tier")
    if tier_data and tier_data["audited"] >= _RULES["tier"]["min_audited"]:
        win_pct = tier_data["would_win_pct"]
        if win_pct is not None:
            allowed = list(current_cfg.get("allowed_tiers", ["STRONG"]))
            if win_pct > _RULES["tier"]["loosen_would_win_pct"]:
                tier_delta_12h = _window_delta(meta, now, "tier_delta", 12)
                add_count = max(1, int((win_pct - 60) / 15))
                to_add = []
                for t in _TIER_ORDER:
                    if t not in allowed and tier_delta_12h + len(to_add) < _RATE_LIMITS["tier_12h"]:
                        to_add.append(t)
                    if len(to_add) >= add_count:
                        break
                if to_add:
                    adjustments["allowed_tiers_add"] = to_add
                    reasons.append(f"tier {win_pct}% would_win (n={tier_data['audited']}) +{len(to_add)}")
            elif win_pct < _RULES["tier"]["tighten_would_win_pct"]:
                tier_delta_12h = _window_delta(meta, now, "tier_delta", 12)
                if tier_delta_12h > -_RATE_LIMITS["tier_12h"]:
                    for t in reversed(_TIER_ORDER):
                        if t in allowed and len(allowed) > 1:
                            adjustments["allowed_tiers_remove"] = [t]
                            reasons.append(f"tier {win_pct}% would_win (n={tier_data['audited']}) — tighten")
                            break

    # ─── STATUS filter ───────────────────────────────────────────────────────
    status_data = summary.get("status")
    if status_data and status_data["audited"] >= _RULES["status"]["min_audited"]:
        win_pct = status_data["would_win_pct"]
        if win_pct is not None:
            allowed = list(current_cfg.get("allowed_statuses", ["CLEAR"]))
            if win_pct > _RULES["status"]["loosen_would_win_pct"]:
                status_delta_12h = _window_delta(meta, now, "status_delta", 12)
                add_count = max(1, int((win_pct - 60) / 15))
                to_add = []
                for s in _STATUS_ORDER:
                    if s not in allowed and status_delta_12h + len(to_add) < _RATE_LIMITS["status_12h"]:
                        to_add.append(s)
                    if len(to_add) >= add_count:
                        break
                if to_add:
                    adjustments["allowed_statuses_add"] = to_add
                    reasons.append(f"status {win_pct}% would_win (n={status_data['audited']}) +{len(to_add)}")
            elif win_pct < _RULES["status"]["tighten_would_win_pct"]:
                status_delta_12h = _window_delta(meta, now, "status_delta", 12)
                if status_delta_12h > -_RATE_LIMITS["status_12h"]:
                    for s in reversed(_STATUS_ORDER):
                        if s in allowed and len(allowed) > 1:
                            adjustments["allowed_statuses_remove"] = [s]
                            reasons.append(f"status {win_pct}% would_win (n={status_data['audited']}) — tighten")
                            break

    # ─── SCORE filter (proportional) ─────────────────────────────────────────
    score_data = summary.get("score")
    if score_data and score_data["audited"] >= _RULES["score"]["min_audited"]:
        win_pct = score_data["would_win_pct"]
        current_min = current_cfg.get("min_score", 60)
        if win_pct is not None:
            score_24h = _window_delta(meta, now, "min_score_delta", 24)
            lo, hi = _RATE_LIMITS["min_score_24h"]
            if win_pct > _RULES["score"]["loosen_would_win_pct"]:
                proposed = int(-max(1, (win_pct - 55) / 3))
                if score_24h + proposed >= lo:
                    new_val = _clamp(current_min + proposed, *_HARD_BOUNDS["min_score"])
                    actual_delta = new_val - current_min
                    if actual_delta != 0:
                        adjustments["min_score_delta"] = actual_delta
                        reasons.append(f"score {win_pct}% would_win (n={score_data['audited']}) Δ{actual_delta}")
            elif win_pct < _RULES["score"]["tighten_would_win_pct"]:
                proposed = int(max(1, (30 - win_pct) / 3))
                if score_24h + proposed <= hi:
                    new_val = _clamp(current_min + proposed, *_HARD_BOUNDS["min_score"])
                    actual_delta = new_val - current_min
                    if actual_delta != 0:
                        adjustments["min_score_delta"] = actual_delta
                        reasons.append(f"score {win_pct}% would_win (n={score_data['audited']}) — tighten Δ{actual_delta}")

    # ─── CONCURRENT filter (proportional) ────────────────────────────────────
    conc_data = summary.get("concurrent")
    if conc_data and conc_data["audited"] >= _RULES["concurrent"]["min_audited"]:
        win_pct = conc_data["would_win_pct"]
        current_max = current_cfg.get("max_concurrent", 1)
        if win_pct is not None:
            conc_24h = _window_delta(meta, now, "max_concurrent_delta", 24)
            lo, hi = _RATE_LIMITS["max_concurrent_24h"]
            if win_pct > _RULES["concurrent"]["loosen_would_win_pct"]:
                proposed = max(1, int((win_pct - 50) / 10))
                if conc_24h + proposed <= hi:
                    new_val = _clamp(current_max + proposed, *_HARD_BOUNDS["max_concurrent"])
                    actual_delta = new_val - current_max
                    if actual_delta != 0:
                        adjustments["max_concurrent_delta"] = actual_delta
                        reasons.append(f"concurrent {win_pct}% would_win (n={conc_data['audited']}) Δ+{actual_delta}")
            elif win_pct < _RULES["concurrent"]["tighten_would_win_pct"]:
                proposed = -max(1, int((30 - win_pct) / 10))
                if conc_24h + proposed >= lo:
                    new_val = _clamp(current_max + proposed, *_HARD_BOUNDS["max_concurrent"])
                    actual_delta = new_val - current_max
                    if actual_delta != 0:
                        adjustments["max_concurrent_delta"] = actual_delta
                        reasons.append(f"concurrent {win_pct}% would_win (n={conc_data['audited']}) — tighten Δ{actual_delta}")

    # ─── PORTFOLIO filter (proportional) ─────────────────────────────────────
    port_data = summary.get("portfolio")
    if port_data and port_data["audited"] >= _RULES["portfolio"]["min_audited"]:
        win_pct = port_data["would_win_pct"]
        if win_pct is not None:
            port_48h = _window_delta(meta, now, "portfolio_mult", 48)
            lo_mult, hi_mult = _RATE_LIMITS["portfolio_48h"]
            if win_pct > _RULES["portfolio"]["loosen_would_win_pct"]:
                proposed_mult = round(1.0 + (win_pct - 55) / 100, 2)
                if port_48h * proposed_mult <= hi_mult:
                    adjustments["portfolio_limits_mult"] = proposed_mult
                    reasons.append(f"portfolio {win_pct}% would_win (n={port_data['audited']}) ×{proposed_mult}")
            elif win_pct < _RULES["portfolio"]["tighten_would_win_pct"]:
                proposed_mult = round(1.0 - (55 - win_pct) / 100, 2)
                if port_48h * proposed_mult >= lo_mult:
                    adjustments["portfolio_limits_mult"] = proposed_mult
                    reasons.append(f"portfolio {win_pct}% would_win (n={port_data['audited']}) — tighten ×{proposed_mult}")

    # ─── DRIFT filter (proportional) ─────────────────────────────────────────
    drift_data = summary.get("drift")
    current_drift_mult = current_cfg.get("drift_psi_multiplier", 1.0)
    if drift_data and drift_data["audited"] >= _RULES["drift"]["min_audited"]:
        win_pct = drift_data["would_win_pct"]
        if win_pct is not None:
            drift_48h = _window_delta(meta, now, "drift_psi_mult", 48)
            lo_mult, hi_mult = _RATE_LIMITS["drift_psi_48h"]
            if win_pct > _RULES["drift"]["loosen_would_win_pct"]:
                # Never loosen drift filter if it's already expanded (>1.10)
                if current_drift_mult > 1.10:
                    reasons.append(f"drift {win_pct}% would_win — BLOCKED loosen (mult={current_drift_mult:.2f} already high)")
                else:
                    proposed_mult = round(1.0 + (win_pct - 55) / 100, 2)
                    # Cap loosening so final mult never exceeds 1.20
                    max_proposed = 1.20 / max(current_drift_mult, 1.0)
                    proposed_mult = min(proposed_mult, max_proposed)
                    if drift_48h * proposed_mult <= hi_mult:
                        adjustments["drift_psi_multiplier"] = proposed_mult
                        reasons.append(f"drift {win_pct}% would_win (n={drift_data['audited']}) ×{proposed_mult}")
            elif win_pct < _RULES["drift"]["tighten_would_win_pct"]:
                proposed_mult = round(1.0 - (55 - win_pct) / 100, 2)
                if drift_48h * proposed_mult >= lo_mult:
                    adjustments["drift_psi_multiplier"] = proposed_mult
                    reasons.append(f"drift {win_pct}% would_win (n={drift_data['audited']}) — tighten ×{proposed_mult}")

    # ─── KELLY filter (proportional) ─────────────────────────────────────────
    kelly_data = summary.get("kelly")
    if kelly_data and kelly_data["audited"] >= _RULES["kelly"]["min_audited"]:
        win_pct = kelly_data["would_win_pct"]
        if win_pct is not None:
            kelly_48h = _window_delta(meta, now, "kelly_edge_mult", 48)
            lo_mult, hi_mult = _RATE_LIMITS["kelly_edge_48h"]
            if win_pct > _RULES["kelly"]["loosen_would_win_pct"]:
                # Lower edge requirement = more permissive → multiplier < 1
                proposed_mult = round(1.0 - (win_pct - 55) / 100, 2)
                if kelly_48h * proposed_mult >= lo_mult:
                    adjustments["kelly_edge_multiplier"] = proposed_mult
                    reasons.append(f"kelly {win_pct}% would_win (n={kelly_data['audited']}) ×{proposed_mult}")
            elif win_pct < _RULES["kelly"]["tighten_would_win_pct"]:
                proposed_mult = round(1.0 + (55 - win_pct) / 100, 2)
                if kelly_48h * proposed_mult <= hi_mult:
                    adjustments["kelly_edge_multiplier"] = proposed_mult
                    reasons.append(f"kelly {win_pct}% would_win (n={kelly_data['audited']}) — tighten ×{proposed_mult}")

    # ─── ROLLING BETA filter (proportional) ──────────────────────────────────
    beta_data = summary.get("rolling_beta")
    if beta_data and beta_data["audited"] >= _RULES["rolling_beta"]["min_audited"]:
        win_pct = beta_data["would_win_pct"]
        if win_pct is not None:
            beta_48h = _window_delta(meta, now, "rolling_beta_mult", 48)
            lo_mult, hi_mult = _RATE_LIMITS["rolling_beta_48h"]
            if win_pct > _RULES["rolling_beta"]["loosen_would_win_pct"]:
                proposed_mult = round(1.0 + (win_pct - 55) / 100, 2)
                if beta_48h * proposed_mult <= hi_mult:
                    adjustments["rolling_beta_threshold_multiplier"] = proposed_mult
                    reasons.append(f"rolling_beta {win_pct}% would_win (n={beta_data['audited']}) ×{proposed_mult}")
            elif win_pct < _RULES["rolling_beta"]["tighten_would_win_pct"]:
                proposed_mult = round(1.0 - (55 - win_pct) / 100, 2)
                if beta_48h * proposed_mult >= lo_mult:
                    adjustments["rolling_beta_threshold_multiplier"] = proposed_mult
                    reasons.append(f"rolling_beta {win_pct}% would_win (n={beta_data['audited']}) — tighten ×{proposed_mult}")

    # ─── SLIPPAGE filter (proportional) ──────────────────────────────────────
    slip_data = summary.get("slippage")
    if slip_data and slip_data["audited"] >= _RULES["slippage"]["min_audited"]:
        win_pct = slip_data["would_win_pct"]
        if win_pct is not None:
            slip_48h = _window_delta(meta, now, "slippage_abort_mult", 48)
            lo_mult, hi_mult = _RATE_LIMITS["slippage_abort_48h"]
            if win_pct > _RULES["slippage"]["loosen_would_win_pct"]:
                proposed_mult = round(1.0 + (win_pct - 55) / 100, 2)
                if slip_48h * proposed_mult <= hi_mult:
                    adjustments["slippage_abort_ratio_multiplier"] = proposed_mult
                    reasons.append(f"slippage {win_pct}% would_win (n={slip_data['audited']}) ×{proposed_mult}")
            elif win_pct < _RULES["slippage"]["tighten_would_win_pct"]:
                proposed_mult = round(1.0 - (55 - win_pct) / 100, 2)
                if slip_48h * proposed_mult >= lo_mult:
                    adjustments["slippage_abort_ratio_multiplier"] = proposed_mult
                    reasons.append(f"slippage {win_pct}% would_win (n={slip_data['audited']}) — tighten ×{proposed_mult}")

    if adjustments:
        adjustments["_reasons"] = reasons
        adjustments["_ticker"] = ticker
        adjustments["_computed_at"] = now.isoformat()

    return adjustments


def apply_rejection_adjustments_to_config(
    db,
    bot,
    current_cfg: dict,
    adjustments: dict,
) -> dict:
    """
    Apply computed adjustments to a bot config dict with rate-limiting and bounds.
    Mutates current_cfg in place and returns it.
    """
    if not adjustments:
        return current_cfg

    now = datetime.now(timezone.utc)
    meta = _get_meta(current_cfg)
    history = list(meta.get("history", []))

    entry = {
        "at": now.isoformat(),
    }

    # ─── Tiers ───────────────────────────────────────────────────────────────
    if "allowed_tiers_add" in adjustments:
        current = list(current_cfg.get("allowed_tiers", ["STRONG"]))
        for t in adjustments["allowed_tiers_add"]:
            if t not in current:
                current.append(t)
        current_cfg["allowed_tiers"] = current
        entry["tier_delta"] = len(adjustments["allowed_tiers_add"])

    if "allowed_tiers_remove" in adjustments:
        current = list(current_cfg.get("allowed_tiers", ["STRONG"]))
        for t in adjustments["allowed_tiers_remove"]:
            if t in current and len(current) > 1:
                current.remove(t)
        current_cfg["allowed_tiers"] = current
        entry["tier_delta"] = -len(adjustments["allowed_tiers_remove"])

    # ─── Statuses ────────────────────────────────────────────────────────────
    if "allowed_statuses_add" in adjustments:
        current = list(current_cfg.get("allowed_statuses", ["CLEAR"]))
        for s in adjustments["allowed_statuses_add"]:
            if s not in current:
                current.append(s)
        current_cfg["allowed_statuses"] = current
        entry["status_delta"] = len(adjustments["allowed_statuses_add"])

    if "allowed_statuses_remove" in adjustments:
        current = list(current_cfg.get("allowed_statuses", ["CLEAR"]))
        for s in adjustments["allowed_statuses_remove"]:
            if s in current and len(current) > 1:
                current.remove(s)
        current_cfg["allowed_statuses"] = current
        entry["status_delta"] = -len(adjustments["allowed_statuses_remove"])

    # ─── Min score ───────────────────────────────────────────────────────────
    if "min_score_delta" in adjustments:
        current = current_cfg.get("min_score", 60)
        new_val = _clamp(current + adjustments["min_score_delta"], *_HARD_BOUNDS["min_score"])
        current_cfg["min_score"] = new_val
        entry["min_score_delta"] = adjustments["min_score_delta"]

    # ─── Max concurrent ──────────────────────────────────────────────────────
    if "max_concurrent_delta" in adjustments:
        current = current_cfg.get("max_concurrent", 1)
        new_val = _clamp(current + adjustments["max_concurrent_delta"], *_HARD_BOUNDS["max_concurrent"])
        current_cfg["max_concurrent"] = new_val
        entry["max_concurrent_delta"] = adjustments["max_concurrent_delta"]

    # ─── Portfolio limits ────────────────────────────────────────────────────
    if "portfolio_limits_mult" in adjustments:
        mult = adjustments["portfolio_limits_mult"]
        limits = dict(current_cfg.get("portfolio_limits", {}))
        for key in ["max_total_exposure_pct", "max_symbol_exposure_pct", "max_directional_exposure_pct"]:
            if key in limits:
                new_val = _clamp(limits[key] * mult, *_HARD_BOUNDS[key])
                limits[key] = round(new_val, 2)
        current_cfg["portfolio_limits"] = limits
        entry["portfolio_mult"] = mult

    # ─── Drift PSI multiplier ────────────────────────────────────────────────
    if "drift_psi_multiplier" in adjustments:
        mult = adjustments["drift_psi_multiplier"]
        current = current_cfg.get("drift_psi_multiplier", 1.0)
        new_val = _clamp(current * mult, *_HARD_BOUNDS["drift_psi_multiplier"])
        current_cfg["drift_psi_multiplier"] = round(new_val, 2)
        entry["drift_psi_mult"] = mult

    # ─── Kelly edge multiplier ───────────────────────────────────────────────
    if "kelly_edge_multiplier" in adjustments:
        mult = adjustments["kelly_edge_multiplier"]
        current = current_cfg.get("kelly_edge_multiplier", 1.0)
        new_val = _clamp(current * mult, *_HARD_BOUNDS["kelly_edge_multiplier"])
        current_cfg["kelly_edge_multiplier"] = round(new_val, 2)
        entry["kelly_edge_mult"] = mult

    # ─── Rolling beta threshold multiplier ───────────────────────────────────
    if "rolling_beta_threshold_multiplier" in adjustments:
        mult = adjustments["rolling_beta_threshold_multiplier"]
        current = current_cfg.get("rolling_beta_threshold_multiplier", 1.0)
        new_val = _clamp(current * mult, *_HARD_BOUNDS["rolling_beta_threshold_multiplier"])
        current_cfg["rolling_beta_threshold_multiplier"] = round(new_val, 2)
        entry["rolling_beta_mult"] = mult

    # ─── Slippage abort ratio multiplier ─────────────────────────────────────
    if "slippage_abort_ratio_multiplier" in adjustments:
        mult = adjustments["slippage_abort_ratio_multiplier"]
        current = current_cfg.get("slippage_abort_ratio_multiplier", 1.0)
        new_val = _clamp(current * mult, *_HARD_BOUNDS["slippage_abort_ratio_multiplier"])
        current_cfg["slippage_abort_ratio_multiplier"] = round(new_val, 2)
        entry["slippage_abort_mult"] = mult

    # ─── Meta update ─────────────────────────────────────────────────────────
    entry["reasons"] = adjustments.get("_reasons", [])
    history.append(entry)
    # Keep last 50 entries
    history = history[-50:]

    meta["last_calibration_at"] = now.isoformat()
    meta["history"] = history
    current_cfg["rejection_calibration_meta"] = meta

    logger.info(
        f"[REJECTION_FEEDBACK] Applied adjustments for bot={bot.bot_name if bot else 'unknown'}: "
        f"{adjustments.get('_reasons', [])}"
    )

    return current_cfg
