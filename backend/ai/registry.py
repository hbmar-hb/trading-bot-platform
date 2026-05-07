"""Model registry — load and serve the anti-fake classifier.

Thread-safe lazy load: model is read from disk once and cached in memory.
Call invalidate() after retraining to force a reload on next prediction.
"""
from __future__ import annotations

import pickle
import threading
from pathlib import Path
from typing import Optional

MODEL_PATH = Path(__file__).parent / "models" / "anti_fake_v1.pkl"

_lock    = threading.Lock()
_cache: dict = {}


def _load() -> dict:
    with _lock:
        if not _cache and MODEL_PATH.exists():
            with open(MODEL_PATH, "rb") as f:
                _cache.update(pickle.load(f))
    return _cache


def model_ready() -> bool:
    return MODEL_PATH.exists()


def model_info() -> dict:
    data = _load()
    if not data:
        return {"ready": False, "path": str(MODEL_PATH)}
    return {
        "ready":              True,
        "trained_on":         data.get("trained_on"),
        "metrics":            data.get("metrics", {}),
        "feature_importance": data.get("feature_importance", {}),
        "feature_names":      data.get("feature_names", []),
    }


def predict_fake_probability(features: dict) -> Optional[float]:
    """
    Returns probability 0–1 that the signal is fake (FAILURE).
    Returns None if the model is not trained yet.
    """
    data = _load()
    if not data or "model" not in data:
        return None

    import pandas as pd

    feature_names = data["feature_names"]
    row = {feat: features.get(feat, 0) for feat in feature_names}
    X   = pd.DataFrame([row])
    return float(data["model"].predict_proba(X)[0, 1])


def invalidate() -> None:
    """Force reload on next call (e.g. after retraining)."""
    with _lock:
        _cache.clear()
