"""Platt Scaling / Isotonic Regression for confidence calibration.

Transforms raw model probabilities (success_probability) into well-calibrated
confidence scores. If the model says P=0.80, a well-calibrated model means
~80% of those signals should actually fail.

Usage:
    from app.services.platt_scaler import train_calibrator, calibrate_probability

    # During training
    calibrator = train_calibrator(raw_probs, true_labels, method="platt")
    save_calibrator(calibrator, path)

    # During inference
    calibrated = calibrate_probability(raw_prob, calibrator)
    # calibrated is in [0,1], directly interpretable
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Literal

import numpy as np
from loguru import logger

# Path where the active calibrator is stored
CALIBRATOR_PATH = Path(__file__).parent.parent / "ai" / "models" / "calibrator.pkl"
META_PATH = Path(__file__).parent.parent / "ai" / "models" / "calibrator_meta.json"


def train_calibrator(
    raw_probs: np.ndarray,
    true_labels: np.ndarray,
    method: Literal["platt", "isotonic"] = "platt",
) -> dict:
    """Train a probability calibrator on validation data.

    Args:
        raw_probs: raw model probabilities (e.g. XGBoost predict_proba), shape (n,)
        true_labels: binary ground-truth labels (0=success, 1=failure), shape (n,)
        method: "platt" (LogisticRegression on probs) or "isotonic" (IsotonicRegression)

    Returns:
        dict with {"calibrator": fitted_model, "method": str, "metrics": {...}}
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import brier_score_loss, log_loss

    # Reshape for sklearn
    X = np.asarray(raw_probs).reshape(-1, 1)
    y = np.asarray(true_labels).astype(int)

    # Clip to avoid log(0)
    X_clipped = np.clip(X, 1e-15, 1 - 1e-15)

    if method == "platt":
        # Platt scaling: logistic regression on log-odds of raw prob
        # Standard approach: fit LR on raw prob (or logit)
        calibrator = LogisticRegression(C=1e10, solver="lbfgs", max_iter=1000)
        calibrator.fit(X_clipped, y)
    elif method == "isotonic":
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(X_clipped.ravel(), y)
    else:
        raise ValueError(f"Unknown calibration method: {method}")

    # Evaluate calibration
    calibrated = calibrate_probability_array(raw_probs, calibrator)
    brier = brier_score_loss(y, raw_probs)
    brier_cal = brier_score_loss(y, calibrated)
    logloss_raw = log_loss(y, np.clip(raw_probs, 1e-15, 1 - 1e-15))
    logloss_cal = log_loss(y, calibrated)

    metrics = {
        "method": method,
        "samples": len(y),
        "base_rate": float(y.mean()),
        "mean_raw_prob": float(raw_probs.mean()),
        "mean_calibrated": float(calibrated.mean()),
        "brier_score_raw": round(brier, 4),
        "brier_score_calibrated": round(brier_cal, 4),
        "logloss_raw": round(logloss_raw, 4),
        "logloss_calibrated": round(logloss_cal, 4),
        "improvement_brier": round(brier - brier_cal, 4),
    }

    logger.info(
        f"[PLATT] Calibrator trained — method={method} "
        f"brier_raw={brier:.4f} brier_cal={brier_cal:.4f} "
        f"improvement={brier - brier_cal:+.4f}"
    )

    return {"calibrator": calibrator, "method": method, "metrics": metrics}


def calibrate_probability_array(
    raw_probs: np.ndarray,
    calibrator,
) -> np.ndarray:
    """Apply calibration to an array of raw probabilities."""
    from sklearn.isotonic import IsotonicRegression

    X = np.asarray(raw_probs).reshape(-1, 1)
    X_clipped = np.clip(X, 1e-15, 1 - 1e-15)

    if isinstance(calibrator, IsotonicRegression):
        return calibrator.predict(X_clipped.ravel())
    else:
        # LogisticRegression
        return calibrator.predict_proba(X_clipped)[:, 1]


def calibrate_probability(raw_prob: float, calibrator) -> float:
    """Apply calibration to a single probability."""
    return float(calibrate_probability_array(np.array([raw_prob]), calibrator)[0])


def save_calibrator(calibrator_data: dict, path: Path | None = None) -> None:
    """Persist calibrator + metadata to disk."""
    path = path or CALIBRATOR_PATH
    meta = calibrator_data.get("metrics", {})
    meta["method"] = calibrator_data.get("method", "platt")

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(calibrator_data["calibrator"], f)

    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, indent=2))

    logger.info(f"[PLATT] Calibrator saved to {path}")


def load_calibrator(path: Path | None = None):
    """Load calibrator from disk. Returns None if not found."""
    path = path or CALIBRATOR_PATH
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception as exc:
        logger.warning(f"[PLATT] Failed to load calibrator: {exc}")
        return None


def load_calibrator_meta() -> dict:
    """Load calibrator metadata."""
    if not META_PATH.exists():
        return {}
    try:
        return json.loads(META_PATH.read_text())
    except Exception:
        return {}
