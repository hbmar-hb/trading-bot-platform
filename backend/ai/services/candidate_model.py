"""Candidate model loader/predictor for Fase D shadow mode.

The candidate is trained offline by scripts/train_candidate_model.py and saved
beside the live models.  It is NEVER loaded automatically by the production
pipeline.  ai_scanner.py checks for its existence and records shadow
predictions when present.
"""
from __future__ import annotations

import pickle
import threading
from pathlib import Path
from typing import Optional

import pandas as pd

_CANDIDATE_PATH = Path(__file__).parent.parent / "models" / "candidate_anti_fake_v1.pkl"
_lock = threading.Lock()
_cache: dict = {}


def _load() -> dict:
    with _lock:
        if not _cache and _CANDIDATE_PATH.exists():
            with open(_CANDIDATE_PATH, "rb") as f:
                _cache.update(pickle.load(f))
    return _cache


def invalidate() -> None:
    with _lock:
        _cache.clear()


def model_ready() -> bool:
    return bool(_load())


def predict_success_probability(features: dict) -> Optional[float]:
    """Return candidate P(success) = 1 - P(fake), mirroring live anti-fake logic."""
    data = _load()
    if not data or "model" not in data:
        return None

    model = data["model"]
    feature_names = data.get("feature_names", [])

    derived = {
        "trigger_ob": int(features.get("trigger", "") == "ob"),
        "trigger_fvg": int(features.get("trigger", "") == "fvg"),
        "bias_bull": int(features.get("bias", "") == "bull"),
        "sweep_bool": int(bool(features.get("sweep_detected", False))),
        "break_choch": int(features.get("break_type", "") == "CHoCH"),
        "htf_bias_bull": int(features.get("htf_bias", "") == "bull"),
        "htf_aligned": int(bool(features.get("htf_aligned", False))),
        "entry_type_re": int(features.get("entry_type", "") == "RE"),
        "ltf_cdc_confirmed": int(bool(features.get("ltf_cdc_confirmed", False))),
        # Fase A macro features
        "nwog_aligned": int(bool((features.get("macro_context") or {}).get("nwog_aligned", False))),
        "org_aligned": int(bool((features.get("macro_context") or {}).get("org_aligned", False))),
        "bisi_present": int(bool((features.get("macro_context") or {}).get("bisi_present", False))),
        "sibi_present": int(bool((features.get("macro_context") or {}).get("sibi_present", False))),
        "ifvg_present": int(bool((features.get("macro_context") or {}).get("ifvg_present", False))),
        "nwog_mitigated": int(bool((features.get("macro_context") or {}).get("nwog_mitigated", False))),
        "org_mitigated": int(bool((features.get("macro_context") or {}).get("org_mitigated", False))),
        "nwog_distance_pct": float((features.get("macro_context") or {}).get("nwog_distance_pct", 0.0) or 0.0),
        "org_distance_pct": float((features.get("macro_context") or {}).get("org_distance_pct", 0.0) or 0.0),
        "macro_bonus": float(features.get("macro_bonus", 0.0) or 0.0),
    }

    row = {feat: derived.get(feat, features.get(feat, 0)) for feat in feature_names}
    X = pd.DataFrame([row])
    fake_prob = float(model.predict_proba(X)[0, 1])
    return 1.0 - fake_prob


def get_feature_importance() -> dict:
    data = _load()
    return data.get("feature_importance", {}) if data else {}
