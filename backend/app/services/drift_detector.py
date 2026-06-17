"""Feature Drift Detector using Population Stability Index (PSI).

Hierarchy: L1 Risk — if drift is severe, degrade or pause trading.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any
from pathlib import Path

from loguru import logger
from sqlalchemy import func

# PSI thresholds (industry standard)
_PSI_HEALTHY = 0.20
_PSI_DEGRADED = 0.30
_PSI_PAUSED = 0.40

# Number of bins for PSI computation
_N_BINS = 10

# Minimum samples needed for reliable PSI
_MIN_SAMPLES = 30

# Features to monitor (must be numeric in AISignal.features)
_MONITORED_FEATURES = [
    "rsi_14",
    "atr_value",
    "volume_ratio",
    "bb_position",
    "macd_hist",
    "ema_slope_20",
    "price_vs_vwap",
    "momentum_10",
]


def _get_reference_path(ticker: str, timeframe: str, model_id: str) -> Path:
    """Path to store reference distributions."""
    base = Path("/app/data/drift_reference")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{ticker}_{timeframe}_{model_id}.json"


def _compute_bins(values: list[float], n_bins: int = _N_BINS) -> list[float]:
    """Compute bin edges from reference distribution (percentile-based).

    Deduplicates edges and adds a micro-epsilon to avoid zero-width bins,
    which would otherwise cause distribution spikes that inflate PSI.
    """
    if len(values) < n_bins:
        # Fallback to equal-width bins across the range
        min_v, max_v = min(values), max(values)
        step = (max_v - min_v) / n_bins if max_v > min_v else 1.0
        return [min_v + step * i for i in range(n_bins + 1)]

    sorted_vals = sorted(values)
    edges = []
    for i in range(n_bins + 1):
        idx = int(len(sorted_vals) * i / n_bins)
        idx = min(idx, len(sorted_vals) - 1)
        edges.append(sorted_vals[idx])
    # Ensure last edge is max
    edges[-1] = sorted_vals[-1]

    # Deduplicate and enforce minimum epsilon between consecutive edges
    _EPS = 1e-9
    deduped = [edges[0]]
    for e in edges[1:]:
        if e > deduped[-1] + _EPS:
            deduped.append(e)
        else:
            deduped.append(deduped[-1] + _EPS)
    # Ensure the final edge captures the true max value
    deduped[-1] = max(deduped[-1], sorted_vals[-1] + _EPS)
    return deduped


def _compute_distribution(values: list[float], bins: list[float]) -> list[float]:
    """Compute probability distribution over bins.

    Handles zero-width bins by redirecting values to the nearest neighbour
    with a non-zero width, preventing artificial mass accumulation in the
    last bin that would inflate PSI.
    """
    if not values:
        return [0.0] * (len(bins) - 1)

    counts = [0] * (len(bins) - 1)
    for v in values:
        assigned = False
        for i in range(len(bins) - 1):
            width = bins[i + 1] - bins[i]
            if width <= 0:
                # Zero-width bin — skip, value will land in a neighbour
                continue
            if bins[i] <= v < bins[i + 1]:
                counts[i] += 1
                assigned = True
                break
        if not assigned:
            # Value is exactly on the last edge (or fell through zero-width bins)
            counts[-1] += 1

    total = sum(counts)
    if total == 0:
        return [0.0] * len(counts)
    return [c / total for c in counts]


def calculate_psi(expected: list[float], actual: list[float]) -> float:
    """Compute Population Stability Index.

    PSI = sum( (Actual% - Expected%) * ln(Actual% / Expected%) )
    """
    if len(expected) != len(actual):
        raise ValueError("Expected and actual distributions must have same length")

    psi = 0.0
    for e, a in zip(expected, actual):
        # Smooth zeros
        e = max(e, 0.0001)
        a = max(a, 0.0001)
        psi += (a - e) * math.log(a / e)
    return psi


@dataclass(frozen=True)
class DriftReport:
    """Result of drift detection for a single model/feature set."""

    model_id: str
    ticker: str
    timeframe: str
    timestamp: str
    overall_status: str  # HEALTHY | DEGRADED | PAUSED
    max_psi: float
    features: dict[str, dict]
    """Per-feature: {psi, status, bins, ref_dist, actual_dist}."""

    action: str
    """Recommended action: proceed | reduce_sizing_50 | pause_trading | retrain."""


def build_reference_distribution(
    db,
    ticker: str,
    timeframe: str,
    model_id: str,
    lookback_days: int = 60,
) -> dict[str, Any]:
    """Build reference distribution from historical AI signals.

    Stores the result to disk for future drift checks.
    """
    from app.models.ai_signal import AISignal

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    signals = (
        db.query(AISignal)
        .filter(
            AISignal.ticker == ticker,
            AISignal.timeframe == timeframe,
            AISignal.signal_time >= cutoff,
            AISignal.features.isnot(None),
        )
        .all()
    )

    if len(signals) < _MIN_SAMPLES:
        logger.warning(
            f"[DRIFT] Insufficient reference data for {ticker}/{timeframe}: "
            f"{len(signals)} < {_MIN_SAMPLES}"
        )
        return {"error": "insufficient_data", "count": len(signals)}

    reference = {}
    for feat in _MONITORED_FEATURES:
        values = []
        for sig in signals:
            if sig.features and feat in sig.features:
                v = sig.features[feat]
                if isinstance(v, (int, float)) and not math.isnan(v):
                    values.append(float(v))

        if len(values) < _MIN_SAMPLES:
            continue

        bins = _compute_bins(values)
        dist = _compute_distribution(values, bins)
        reference[feat] = {
            "bins": bins,
            "distribution": dist,
            "mean": sum(values) / len(values),
            "std": (sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values)) ** 0.5,
            "count": len(values),
        }

    ref_data = {
        "model_id": model_id,
        "ticker": ticker,
        "timeframe": timeframe,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "features": reference,
    }

    path = _get_reference_path(ticker, timeframe, model_id)
    path.write_text(json.dumps(ref_data, indent=2))
    logger.info(
        f"[DRIFT] Reference distribution built for {ticker}/{timeframe}: "
        f"{len(reference)} features, {len(signals)} signals"
    )
    return ref_data


def load_reference_distribution(
    ticker: str, timeframe: str, model_id: str
) -> dict[str, Any] | None:
    """Load reference distribution from disk."""
    path = _get_reference_path(ticker, timeframe, model_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        logger.warning(f"[DRIFT] Failed to load reference: {exc}")
        return None


def check_feature_drift(
    db,
    ticker: str,
    timeframe: str,
    model_id: str,
    lookback_days: int = 7,
) -> DriftReport:
    """Check for feature drift by comparing recent signals to reference.

    Returns a DriftReport with per-feature PSI and overall status.
    """
    reference = load_reference_distribution(ticker, timeframe, model_id)
    if reference is None:
        logger.info(
            f"[DRIFT] No reference found for {ticker}/{timeframe}, building..."
        )
        reference = build_reference_distribution(db, ticker, timeframe, model_id)
        if "error" in reference:
            return DriftReport(
                model_id=model_id,
                ticker=ticker,
                timeframe=timeframe,
                timestamp=datetime.now(timezone.utc).isoformat(),
                overall_status="UNKNOWN",
                max_psi=0.0,
                features={},
                action="build_reference",
            )
        # Fresh reference just built — no drift possible against itself.
        # Return HEALTHY for this check cycle.
        return DriftReport(
            model_id=model_id,
            ticker=ticker,
            timeframe=timeframe,
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall_status="HEALTHY",
            max_psi=0.0,
            features={},
            action="proceed",
        )

    from app.models.ai_signal import AISignal

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    recent_signals = (
        db.query(AISignal)
        .filter(
            AISignal.ticker == ticker,
            AISignal.timeframe == timeframe,
            AISignal.signal_time >= cutoff,
            AISignal.features.isnot(None),
        )
        .all()
    )

    if len(recent_signals) < _MIN_SAMPLES:
        logger.info(
            f"[DRIFT] Insufficient recent data for {ticker}/{timeframe}: "
            f"{len(recent_signals)} < {_MIN_SAMPLES}"
        )
        return DriftReport(
            model_id=model_id,
            ticker=ticker,
            timeframe=timeframe,
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall_status="HEALTHY",  # Not enough data to declare drift
            max_psi=0.0,
            features={},
            action="proceed",
        )

    ref_features = reference.get("features", {})
    feature_reports = {}
    max_psi = 0.0

    for feat in _MONITORED_FEATURES:
        if feat not in ref_features:
            continue

        ref_bins = ref_features[feat]["bins"]
        ref_dist = ref_features[feat]["distribution"]

        actual_values = []
        for sig in recent_signals:
            if sig.features and feat in sig.features:
                v = sig.features[feat]
                if isinstance(v, (int, float)) and not math.isnan(v):
                    actual_values.append(float(v))

        if len(actual_values) < 10:
            continue

        actual_dist = _compute_distribution(actual_values, ref_bins)
        psi = calculate_psi(ref_dist, actual_dist)

        if psi > max_psi:
            max_psi = psi

        if psi < _PSI_HEALTHY:
            status = "HEALTHY"
        elif psi < _PSI_DEGRADED:
            status = "DEGRADED"
        elif psi < _PSI_PAUSED:
            status = "PAUSED"
        else:
            status = "CRITICAL"

        feature_reports[feat] = {
            "psi": round(psi, 4),
            "status": status,
            "ref_mean": round(ref_features[feat]["mean"], 4),
            "actual_mean": round(sum(actual_values) / len(actual_values), 4),
            "ref_std": round(ref_features[feat]["std"], 4),
            "actual_std": round(
                (sum((v - sum(actual_values) / len(actual_values)) ** 2 for v in actual_values)
                 / len(actual_values)) ** 0.5,
                4,
            ),
        }

    # Overall status is the WORST across features
    status_priority = ["HEALTHY", "DEGRADED", "PAUSED", "CRITICAL"]
    worst_status = "HEALTHY"
    for feat_report in feature_reports.values():
        if status_priority.index(feat_report["status"]) > status_priority.index(worst_status):
            worst_status = feat_report["status"]

    if worst_status == "HEALTHY":
        action = "proceed"
    elif worst_status == "DEGRADED":
        action = "reduce_sizing_50"
    elif worst_status == "PAUSED":
        action = "pause_trading"
    else:
        action = "retrain"

    report = DriftReport(
        model_id=model_id,
        ticker=ticker,
        timeframe=timeframe,
        timestamp=datetime.now(timezone.utc).isoformat(),
        overall_status=worst_status,
        max_psi=round(max_psi, 4),
        features=feature_reports,
        action=action,
    )

    logger.info(
        f"[DRIFT] {ticker}/{timeframe}: status={worst_status} max_psi={max_psi:.4f} "
        f"action={action} features={len(feature_reports)}"
    )
    return report


def get_drift_status_for_signal(
    db,
    ticker: str,
    timeframe: str,
    model_id: str,
    user_cfg: dict | None = None,
) -> dict:
    """Quick check for bot activator — returns gate info.
    
    Accepts user_cfg with drift_psi_multiplier to loosen/tighten thresholds.
    """
    report = check_feature_drift(db, ticker, timeframe, model_id, lookback_days=7)
    psi = report.max_psi

    # Apply per-bot calibration multiplier
    mult = float(user_cfg.get("drift_psi_multiplier", 1.0)) if user_cfg else 1.0
    healthy_th = _PSI_HEALTHY * mult
    degraded_th = _PSI_DEGRADED * mult
    paused_th = _PSI_PAUSED * mult

    if psi >= paused_th:
        return {
            "blocked": True,
            "degraded": False,
            "sizing_multiplier": 0.0,
            "reason": f"drift_PAUSED (psi={psi:.3f}, mult={mult:.2f})",
            "max_psi": psi,
            "action": "retrain",
        }

    if psi >= degraded_th:
        return {
            "blocked": False,
            "degraded": True,
            "sizing_multiplier": 0.5,
            "reason": f"drift_DEGRADED (psi={psi:.3f}, mult={mult:.2f})",
            "max_psi": psi,
            "action": "reduce_sizing_50",
        }

    return {
        "blocked": False,
        "degraded": False,
        "sizing_multiplier": 1.0,
        "reason": None,
        "max_psi": psi,
        "action": "proceed",
    }
