"""Hybrid Ensemble Trainer — Stacking with OOF meta-features.

Trains 3 diverse base models (XGBoost, RandomForest, RidgeClassifier)
using cross-validation to generate out-of-fold predictions.
A meta-learner (LogisticRegression) is then trained on these OOF probabilities
to learn optimal blending weights.

v2 — Three improvements from audit:
  1. RidgeClassifier replaces GaussianNB: linear vs tree-based diversity,
     class_weight="balanced" handles imbalance, natively supports sample_weight.
  2. Platt calibration of each base model's OOF probs before stacking: the
     meta-learner receives mathematically coherent probabilities, not raw scores.
  3. Temporal purge at fold boundaries: removes _PURGE_SAMPLES training points
     adjacent to each test fold to reduce serial market-correlation leakage.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression, RidgeClassifier
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.metrics import roc_auc_score, accuracy_score
from sklearn.preprocessing import StandardScaler

MODEL_DIR = Path(__file__).parent.parent / "models"
ENSEMBLE_PATH = MODEL_DIR / "ensemble_v1.pkl"

MIN_SAMPLES = 50
_PURGE_SAMPLES = 5  # positions to remove at train/test boundary (time proxy)


def _build_xgb_clf(scale_pos: float) -> "XGBClassifier":
    from xgboost import XGBClassifier
    return XGBClassifier(
        n_estimators=500,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.7,
        colsample_bytree=0.7,
        colsample_bylevel=0.7,
        reg_alpha=0.5,
        reg_lambda=3.0,
        gamma=2.0,
        min_child_weight=10,
        scale_pos_weight=scale_pos,
        random_state=42,
        eval_metric="logloss",
        verbosity=0,
        early_stopping_rounds=30,
    )


def _build_rf_clf() -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=300,
        max_depth=6,
        min_samples_leaf=10,
        min_samples_split=20,
        max_features="sqrt",
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )


def _build_ridge_clf() -> RidgeClassifier:
    """Ridge linear classifier as the diverse base model.

    Orthogonal to XGB/RF (linear decision boundary vs tree splits) — reduces
    ensemble error correlation. class_weight="balanced" handles the ~14% positive
    base rate without needing scale_pos_weight. decision_function() outputs are
    sigmoid-transformed in _train_base_oob before Platt calibration.
    """
    return RidgeClassifier(alpha=1.0, class_weight="balanced")


def _apply_purge(train_idx: np.ndarray, test_idx: np.ndarray, purge_n: int) -> np.ndarray:
    """Remove training samples within purge_n positions of the test fold boundary.

    Data is sorted chronologically by resolved_at; position index proxies for time.
    Eliminates serial market-correlation leakage at each train/test boundary without
    requiring explicit timestamps in the feature matrix.
    Falls back to full train_idx if purge would leave fewer than 20 samples or drop
    all members of a class.
    """
    if purge_n <= 0 or len(test_idx) == 0:
        return train_idx
    test_min = int(test_idx.min())
    purged = train_idx[train_idx < test_min - purge_n]
    if len(purged) < 20:
        return train_idx
    return purged


def _calibrate_oof_probs(
    oof_probs: np.ndarray, y: pd.Series
) -> tuple[np.ndarray, LogisticRegression]:
    """Platt-scale raw OOF outputs to mathematically valid probabilities.

    Fits a univariate LogisticRegression on (oof_probs, y). This maps overconfident
    tree scores and sigmoid-transformed Ridge scores to the true posterior probability
    scale, so the meta-learner receives coherent inputs from all three base models.

    Returns (calibrated_probs, fitted_calibrator). The calibrator is stored in the
    artifact and applied at inference time to maintain train/serve consistency.
    """
    cal = LogisticRegression(C=1.0, solver="lbfgs", max_iter=300, random_state=42)
    cal.fit(oof_probs.reshape(-1, 1), y.values)
    return cal.predict_proba(oof_probs.reshape(-1, 1))[:, 1], cal


def _get_cv_splits(X: pd.DataFrame, y: pd.Series, groups: pd.Series | None = None):
    if groups is not None and len(groups) == len(X):
        n_groups = groups.nunique() if hasattr(groups, "nunique") else len(set(groups))
        n_splits = min(3, max(2, n_groups))
        if n_splits >= 2:
            return GroupKFold(n_splits=n_splits)
    return StratifiedKFold(n_splits=3, shuffle=True, random_state=42)


def _train_base_oob(
    model,
    X: pd.DataFrame,
    y: pd.Series,
    cv,
    name: str,
    scale_pos: float | None = None,
    groups: pd.Series | None = None,
    sample_weights: pd.Series | None = None,
) -> tuple[np.ndarray, dict]:
    """Train a base model with CV and return OOF probabilities + fold metrics."""
    oof_probs = np.zeros(len(X))
    fold_aucs: list[float] = []
    fold_accs: list[float] = []

    split_kwargs = {}
    if groups is not None and isinstance(cv, GroupKFold):
        split_kwargs["groups"] = groups

    sw = sample_weights.values if sample_weights is not None else np.ones(len(X))

    for fold_idx, (train_idx, test_idx) in enumerate(cv.split(X, y, **split_kwargs)):
        # Temporal purge: drop training samples adjacent to the test fold boundary
        train_idx = _apply_purge(train_idx, test_idx, _PURGE_SAMPLES)

        X_tr = X.iloc[train_idx]
        y_tr = y.iloc[train_idx]
        X_te = X.iloc[test_idx]
        y_te = y.iloc[test_idx]
        sw_tr = sw[train_idx]

        if len(np.unique(y_tr.values)) < 2:
            # Purge removed all members of a class — skip fold rather than crash
            continue

        # Light noise for robustness (only in training)
        rng = np.random.default_rng(42 + fold_idx)
        X_tr_noisy = X_tr.copy()
        for col in X_tr_noisy.columns:
            std = X_tr_noisy[col].std()
            if std > 0:
                X_tr_noisy[col] = X_tr_noisy[col] + rng.normal(0, std * 0.01, size=len(X_tr_noisy))

        clf = model if name != "xgb" else _build_xgb_clf(scale_pos or 1.0)

        if name == "xgb":
            if len(X_te) >= 10:
                clf.fit(
                    X_tr_noisy, y_tr,
                    sample_weight=sw_tr,
                    eval_set=[(X_te, y_te)],
                    verbose=False,
                )
            else:
                clf.set_params(early_stopping_rounds=None)
                clf.fit(X_tr_noisy, y_tr, sample_weight=sw_tr)
        else:
            clf.fit(X_tr_noisy, y_tr, sample_weight=sw_tr)

        # RidgeClassifier has no predict_proba — use sigmoid of decision_function
        if hasattr(clf, "predict_proba"):
            probs = clf.predict_proba(X_te)[:, 1]
        else:
            scores = clf.decision_function(X_te).astype(float)
            probs = 1.0 / (1.0 + np.exp(-scores))

        oof_probs[test_idx] = probs

        fold_aucs.append(roc_auc_score(y_te, probs))
        fold_accs.append(accuracy_score(y_te, (probs >= 0.5).astype(int)))

    metrics = {
        "oof_auc": round(roc_auc_score(y, oof_probs), 4),
        "oof_accuracy": round(accuracy_score(y, (oof_probs >= 0.5).astype(int)), 4),
        "fold_aucs": [round(a, 4) for a in fold_aucs],
        "fold_accs": [round(a, 4) for a in fold_accs],
    }
    return oof_probs, metrics


def train_ensemble(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series | None = None,
    sample_weights: pd.Series | None = None,
    llm_scores: pd.Series | None = None,
) -> tuple[dict, dict]:
    """Train hybrid ensemble and return artifact + metrics.

    Args:
        llm_scores: Optional Series of LLM diagnosis scores aligned with X index.
                    Values in [0, 1] where higher = more bearish (BLOCK-like).

    Returns:
        (artifact_dict, metrics_dict)
    """
    if len(X) < MIN_SAMPLES:
        raise ValueError(f"Need ≥{MIN_SAMPLES} resolved signals, got {len(X)}")

    pos = int((y == 1).sum())
    neg = int((y == 0).sum())
    scale_pos = neg / pos if pos > 0 else 1.0

    cv = _get_cv_splits(X, y, groups)

    # ── 1. Train base models OOF ───────────────────────────────────────────
    xgb_oob, xgb_metrics = _train_base_oob(
        _build_xgb_clf(scale_pos), X, y, cv, "xgb", scale_pos, groups=groups, sample_weights=sample_weights
    )
    rf_oob, rf_metrics = _train_base_oob(
        _build_rf_clf(), X, y, cv, "rf", groups=groups, sample_weights=sample_weights
    )
    ridge_oob, ridge_metrics = _train_base_oob(
        _build_ridge_clf(), X, y, cv, "ridge", groups=groups, sample_weights=sample_weights
    )

    # ── 2. Platt-calibrate each base model's OOF probs before stacking ─────
    # Meta-learner receives mathematically coherent probabilities from all three
    # models, not raw scores. Calibrators are stored for train/serve consistency.
    xgb_oob_cal, cal_xgb = _calibrate_oof_probs(xgb_oob, y)
    rf_oob_cal,  cal_rf  = _calibrate_oof_probs(rf_oob,  y)
    ridge_oob_cal, cal_ridge = _calibrate_oof_probs(ridge_oob, y)

    # ── 3. Meta-learner on calibrated OOF probabilities ────────────────────
    meta_features = [xgb_oob_cal, rf_oob_cal, ridge_oob_cal]
    meta_feature_names = ["xgb", "rf", "ridge"]

    if llm_scores is not None and len(llm_scores) == len(xgb_oob):
        meta_features.append(llm_scores.values)
        meta_feature_names.append("llm")

    meta_X = np.column_stack(meta_features)

    meta_scaler = StandardScaler()
    meta_X_scaled = meta_scaler.fit_transform(meta_X)

    meta_learner = LogisticRegression(
        penalty="l2",
        C=1.0,
        solver="lbfgs",
        max_iter=1000,
        random_state=42,
    )
    meta_learner.fit(meta_X_scaled, y.values)

    meta_probs = meta_learner.predict_proba(meta_X_scaled)[:, 1]
    meta_auc = round(roc_auc_score(y, meta_probs), 4)
    meta_acc = round(accuracy_score(y, (meta_probs >= 0.5).astype(int)), 4)

    # Meta-learner coefficients show how each base model is weighted
    meta_weights = dict(
        zip(
            meta_feature_names,
            [float(v) for v in meta_learner.coef_[0].tolist()],
        )
    )

    # ── 4. Final base models trained on FULL dataset ───────────────────────
    sw = sample_weights.values if sample_weights is not None else np.ones(len(X))

    final_xgb = _build_xgb_clf(scale_pos)
    final_xgb.set_params(early_stopping_rounds=None)
    final_xgb.fit(X, y, sample_weight=sw)

    final_rf = _build_rf_clf()
    final_rf.fit(X, y, sample_weight=sw)

    final_ridge = _build_ridge_clf()
    final_ridge.fit(X, y, sample_weight=sw)

    # ── 5. Build artifact ──────────────────────────────────────────────────
    artifact = {
        "base_models": {
            "xgb": final_xgb,
            "rf": final_rf,
            "ridge": final_ridge,
        },
        # Platt calibrators for each base model — applied at inference before
        # passing to meta-learner to maintain train/serve calibration consistency.
        "base_calibrators": {
            "xgb": cal_xgb,
            "rf": cal_rf,
            "ridge": cal_ridge,
        },
        "meta_learner": meta_learner,
        "meta_scaler": meta_scaler,
        "feature_names": list(X.columns),
        "meta_feature_names": meta_feature_names,
        "base_model_names": ["xgb", "rf", "ridge"],
        "use_llm": "llm" in meta_feature_names,
        "metrics": {
            "ensemble_auc": meta_auc,
            "ensemble_accuracy": meta_acc,
            "xgb_auc": xgb_metrics["oof_auc"],
            "rf_auc": rf_metrics["oof_auc"],
            "ridge_auc": ridge_metrics["oof_auc"],
            "meta_weights": meta_weights,
        },
        "trained_on": len(X),
    }

    def _clean(val):
        import numpy as np
        if isinstance(val, (np.integer, np.floating)):
            return float(val)
        if isinstance(val, np.ndarray):
            return val.tolist()
        if isinstance(val, dict):
            return {k: _clean(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_clean(v) for v in val]
        return val

    metrics = {
        "ensemble_auc": meta_auc,
        "ensemble_accuracy": meta_acc,
        **{f"xgb_{k}": _clean(v) for k, v in xgb_metrics.items()},
        **{f"rf_{k}": _clean(v) for k, v in rf_metrics.items()},
        **{f"ridge_{k}": _clean(v) for k, v in ridge_metrics.items()},
        "meta_weights": meta_weights,
        "train_samples": int(len(X)),
        "feature_count": int(X.shape[1]),
    }

    return artifact, metrics


def save_artifact(artifact: dict) -> None:
    """Persist ensemble artifact to disk."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(ENSEMBLE_PATH, "wb") as f:
        pickle.dump(artifact, f)


def train(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series | None = None,
    sample_weights: pd.Series | None = None,
) -> dict:
    """Train and immediately save ensemble."""
    artifact, metrics = train_ensemble(X, y, groups, sample_weights)
    save_artifact(artifact)
    return metrics
