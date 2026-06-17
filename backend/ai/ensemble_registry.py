"""Ensemble registry — load and serve the hybrid stacking classifier.

Thread-safe lazy load: ensemble is read from disk once and cached in memory.
Call invalidate() after retraining to force a reload on next prediction.
"""
from __future__ import annotations

import pickle
import threading
from pathlib import Path
from typing import Optional

ENSEMBLE_PATH = Path(__file__).parent / "models" / "ensemble_v1.pkl"

_lock = threading.Lock()
_cache: dict = {}


def _load() -> dict:
    with _lock:
        if not _cache and ENSEMBLE_PATH.exists():
            with open(ENSEMBLE_PATH, "rb") as f:
                _cache.update(pickle.load(f))
    return _cache


def model_ready() -> bool:
    return ENSEMBLE_PATH.exists()


def _to_python(obj):
    """Recursively convert numpy scalars to Python native types for JSON serialization."""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_python(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_python(v) for v in obj]
    return obj


def model_info() -> dict:
    data = _load()
    if not data:
        return {"ready": False, "path": str(ENSEMBLE_PATH)}
    return {
        "ready": True,
        "trained_on": data.get("trained_on"),
        "metrics": _to_python(data.get("metrics", {})),
        "feature_names": data.get("feature_names", []),
        "base_models": data.get("base_model_names", []),
    }


def predict_ensemble_probability(features: dict, llm_score: float = 0.5) -> Optional[dict]:
    """
    Returns dict with ensemble and base-model SUCCESS probabilities.

    Base models predict P(FAILURE); we apply their stored Platt calibrators
    before feeding to the meta-learner (train/serve consistency), then invert
    to P(SUCCESS) at the registry boundary.

    Args:
        features: signal feature dict (market-structure + execution-quality features)
        llm_score: LLM diagnosis score in [0, 1] where higher = more bearish/BLOCK-like.
                   Only used if the ensemble was trained with LLM scores.

    Returns:
        {
            "ensemble": float,   # meta-learner blended P(success)
            "xgb": float,        # XGBoost P(success)
            "rf": float,         # RandomForest P(success)
            "ridge": float,      # Ridge linear P(success)
        }
        or None if model not ready.
    """
    data = _load()
    if not data or "meta_learner" not in data:
        return None

    import numpy as np
    import pandas as pd

    feature_names = data["feature_names"]

    # Derive binary/encoded features from raw signal dict (mirrors dataset_builder.py transforms)
    _TF_ORDINAL = {
        "1m": 1, "3m": 2, "5m": 3, "15m": 4, "30m": 5,
        "1h": 6, "2h": 7, "4h": 8, "6h": 9, "8h": 10,
        "12h": 11, "1d": 12, "3d": 13, "1w": 14,
    }
    derived: dict = {
        "trigger_ob":    int(features.get("trigger", "") == "ob"),
        "trigger_fvg":   int(features.get("trigger", "") == "fvg"),
        "bias_bull":     int(features.get("bias", "") == "bull"),
        "sweep_bool":    int(bool(features.get("sweep_detected", False))),
        "break_choch":   int(features.get("break_type", "") == "CHoCH"),
        "htf_bias_bull": int(features.get("htf_bias", "") == "bull"),
        "htf_aligned":   int(bool(features.get("htf_aligned", False))),
        "entry_type_re": int(features.get("entry_type", "") == "RE"),
        "ltf_cdc_confirmed": int(bool(features.get("ltf_cdc_confirmed", False))),
        "timeframe_encoded": _TF_ORDINAL.get(str(features.get("timeframe", "")), 6),
        "is_real_trade": 0,  # live signals are not historical outcomes
    }
    row = {feat: derived.get(feat, features.get(feat, 0)) for feat in feature_names}
    X = pd.DataFrame([row])

    base_models = data["base_models"]
    base_calibrators = data.get("base_calibrators", {})  # absent in pre-v2 pickles
    meta_scaler = data["meta_scaler"]
    meta_learner = data["meta_learner"]
    meta_feature_names = data.get("meta_feature_names", ["xgb", "rf", "ridge"])
    use_llm = data.get("use_llm", False)

    # Base models predict P(FAILURE); apply per-model Platt calibrator for consistency
    fake_probs = {}
    for name, model in base_models.items():
        try:
            if hasattr(model, "predict_proba"):
                raw = float(model.predict_proba(X)[0, 1])
            else:
                # RidgeClassifier: sigmoid of decision_function score
                score = float(model.decision_function(X)[0])
                raw = 1.0 / (1.0 + np.exp(-score))

            cal = base_calibrators.get(name)
            if cal is not None:
                fake_probs[name] = float(cal.predict_proba([[raw]])[0, 1])
            else:
                fake_probs[name] = raw
        except Exception:
            fake_probs[name] = 0.5

    # Build meta-features in training order using meta_feature_names
    meta_values = [fake_probs.get(n, 0.5) for n in meta_feature_names if n != "llm"]
    if use_llm and "llm" in meta_feature_names:
        meta_values.append(float(llm_score))

    meta_input = np.array([meta_values])
    meta_input_scaled = meta_scaler.transform(meta_input)
    ensemble_fake_prob = float(meta_learner.predict_proba(meta_input_scaled)[0, 1])

    # Invert to P(SUCCESS) at the boundary; include all base models dynamically
    result: dict = {"ensemble": 1.0 - ensemble_fake_prob}
    for name in meta_feature_names:
        if name != "llm":
            result[name] = 1.0 - fake_probs.get(name, 0.5)
    return result


def invalidate() -> None:
    """Force reload on next call (e.g. after retraining)."""
    with _lock:
        _cache.clear()
