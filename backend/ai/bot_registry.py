"""Per-bot model registry with global fallback.

Each bot can have its own anti-fake and ensemble models.
If a bot-specific model does not exist, falls back to the global model.
New bots start with the global model and accumulate their own
as soon as they have enough labeled signals (≥100).
"""
from __future__ import annotations

import pickle
import threading
from pathlib import Path
from typing import Optional

from ai import registry as anti_fake_registry
from ai import ensemble_registry

# Bot-specific model paths
_BOT_MODEL_DIR = Path(__file__).parent / "models" / "bots"

_lock = threading.Lock()
_bot_cache: dict[str, dict] = {}


def _bot_model_path(bot_id: str, model_type: str) -> Path:
    return _BOT_MODEL_DIR / bot_id / f"{model_type}.pkl"


def _load_bot_model(bot_id: str, model_type: str) -> dict | None:
    path = _bot_model_path(bot_id, model_type)
    if not path.exists():
        return None
    with _lock:
        cache_key = f"{bot_id}:{model_type}"
        if cache_key not in _bot_cache:
            with open(path, "rb") as f:
                _bot_cache[cache_key] = pickle.load(f)
        return _bot_cache[cache_key]


def model_ready_for_bot(bot_id: str, model_type: str = "anti_fake") -> bool:
    return _bot_model_path(bot_id, model_type).exists()


def get_bot_model_meta(bot_id: str, model_type: str = "anti_fake") -> dict | None:
    """Return metadata dict from a bot model without the heavy model object.

    Returns keys like: trained_on, metrics, feature_names, meta_feature_names, use_llm.
    Returns None if the model file does not exist.
    """
    data = _load_bot_model(bot_id, model_type)
    if data is None:
        return None
    # Strip heavy objects so callers don't accidentally mutate cache
    meta = {k: v for k, v in data.items() if k not in ("model", "meta_learner", "meta_scaler", "base_models", "base_calibrators")}
    return meta


def invalidate_bot(bot_id: str) -> None:
    with _lock:
        keys_to_remove = [k for k in _bot_cache if k.startswith(f"{bot_id}:")]
        for k in keys_to_remove:
            del _bot_cache[k]


def predict_success_probability_for_bot(features: dict, bot_id: str) -> Optional[float]:
    """Return P(success) using bot-specific model if available, else global."""
    bot_data = _load_bot_model(bot_id, "anti_fake")
    if bot_data and "model" in bot_data:
        return _predict_with_data(features, bot_data)
    # Fallback to global
    return anti_fake_registry.predict_success_probability(features)


def predict_ensemble_probability_for_bot(features: dict, bot_id: str, llm_score: float = 0.5) -> Optional[dict]:
    """Return ensemble dict using bot-specific model if available, else global."""
    bot_data = _load_bot_model(bot_id, "ensemble")
    if bot_data and "meta_learner" in bot_data:
        return _predict_ensemble_with_data(features, bot_data, llm_score)
    # Fallback to global
    return ensemble_registry.predict_ensemble_probability(features, llm_score)


def _predict_with_data(features: dict, data: dict) -> Optional[float]:
    import pandas as pd
    feature_names = data["feature_names"]
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
    }
    row = {feat: derived.get(feat, features.get(feat, 0)) for feat in feature_names}
    X = pd.DataFrame([row])
    fake_prob = float(data["model"].predict_proba(X)[0, 1])
    return 1.0 - fake_prob


def _predict_ensemble_with_data(features: dict, data: dict, llm_score: float) -> Optional[dict]:
    import numpy as np
    import pandas as pd

    feature_names = data["feature_names"]
    _TF_ORDINAL = {
        "1m": 1, "3m": 2, "5m": 3, "15m": 4, "30m": 5,
        "1h": 6, "2h": 7, "4h": 8, "6h": 9, "8h": 10,
        "12h": 11, "1d": 12, "3d": 13, "1w": 14,
    }
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
        "timeframe_encoded": _TF_ORDINAL.get(str(features.get("timeframe", "")), 6),
        "is_real_trade": 0,
    }
    row = {feat: derived.get(feat, features.get(feat, 0)) for feat in feature_names}
    X = pd.DataFrame([row])

    base_models = data["base_models"]
    base_calibrators = data.get("base_calibrators", {})
    meta_scaler = data["meta_scaler"]
    meta_learner = data["meta_learner"]
    meta_feature_names = data.get("meta_feature_names", ["xgb", "rf", "ridge"])
    use_llm = data.get("use_llm", False)

    fake_probs = {}
    for name, model in base_models.items():
        try:
            if hasattr(model, "predict_proba"):
                raw = float(model.predict_proba(X)[0, 1])
            else:
                score = float(model.decision_function(X)[0])
                raw = 1.0 / (1.0 + np.exp(-score))
            cal = base_calibrators.get(name)
            if cal is not None:
                fake_probs[name] = float(cal.predict_proba([[raw]])[0, 1])
            else:
                fake_probs[name] = raw
        except Exception:
            fake_probs[name] = 0.5

    meta_values = [fake_probs.get(n, 0.5) for n in meta_feature_names if n != "llm"]
    if use_llm and "llm" in meta_feature_names:
        meta_values.append(float(llm_score))

    meta_input = np.array([meta_values])
    meta_input_scaled = meta_scaler.transform(meta_input)
    ensemble_fake_prob = float(meta_learner.predict_proba(meta_input_scaled)[0, 1])

    result = {"ensemble": 1.0 - ensemble_fake_prob}
    for name in meta_feature_names:
        if name != "llm":
            result[name] = 1.0 - fake_probs.get(name, 0.5)
    return result


def save_bot_model(bot_id: str, model_type: str, payload: dict) -> None:
    """Persist a trained bot-specific model to disk."""
    path = _bot_model_path(bot_id, model_type)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(payload, f)
    invalidate_bot(bot_id)
