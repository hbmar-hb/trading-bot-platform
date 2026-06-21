"""XGBoost Anti-Fake classifier trainer.

Trains a binary classifier on resolved AISignal outcomes:
  y=1 → FAILURE (the signal was a "fake" / losing trade)
  y=0 → SUCCESS (the signal was genuine / winning trade)

Activates automatically when ≥200 resolved signals accumulate.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, classification_report

MODEL_DIR  = Path(__file__).parent.parent / "models"
MODEL_PATH = MODEL_DIR / "anti_fake_v1.pkl"

MIN_SAMPLES = 200


def train_model(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series | None = None,
    sample_weights: pd.Series | None = None,
) -> tuple[dict, dict]:
    """
    Train XGBoost anti-fake classifier and return artifact + metrics.

    Args:
        X: feature matrix (n_samples × n_features)
        y: binary labels (1=fake/failure, 0=real/success)
        groups: optional group labels (currently unused, kept for API compatibility)
        sample_weights: optional per-sample weights passed to XGBClassifier.fit

    Returns:
        (artifact_dict, metrics_dict)
    """
    if len(X) < MIN_SAMPLES:
        raise ValueError(f"Need ≥{MIN_SAMPLES} resolved signals, got {len(X)}")

    from xgboost import XGBClassifier

    pos = int((y == 1).sum())
    neg = int((y == 0).sum())
    scale_pos = neg / pos if pos > 0 else 1.0

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    sw_tr = None
    if sample_weights is not None:
        sw_tr = sample_weights.loc[X_tr.index].values

    clf = XGBClassifier(
        n_estimators      = 150,
        max_depth         = 4,
        learning_rate     = 0.08,
        subsample         = 0.8,
        colsample_bytree  = 0.8,
        scale_pos_weight  = scale_pos,
        random_state      = 42,
        eval_metric       = "logloss",
        verbosity         = 0,
    )
    fit_kwargs = {
        "eval_set": [(X_te, y_te)],
        "verbose": False,
    }
    if sw_tr is not None:
        fit_kwargs["sample_weight"] = sw_tr
    clf.fit(X_tr, y_tr, **fit_kwargs)

    y_prob = clf.predict_proba(X_te)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)
    auc    = round(roc_auc_score(y_te, y_prob), 4)

    report = classification_report(y_te, y_pred, output_dict=True)
    accuracy = round(report["accuracy"], 4)

    feature_importance = dict(
        sorted(
            zip(X.columns, clf.feature_importances_),
            key=lambda x: x[1],
            reverse=True,
        )
    )

    artifact = {
        "model":            clf,
        "feature_names":    list(X.columns),
        "metrics":          {"auc": auc, "accuracy": accuracy},
        "feature_importance": feature_importance,
        "trained_on":       len(X),
    }

    metrics = {
        "auc":           auc,
        "accuracy":      accuracy,
        "train_samples": len(X_tr),
        "test_samples":  len(X_te),
        "feature_count": X.shape[1],
        "top_features":  list(feature_importance.keys())[:5],
    }
    return artifact, metrics


def save_artifact(artifact: dict) -> None:
    """Persist anti-fake artifact to disk."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(artifact, f)


def train(X: pd.DataFrame, y: pd.Series) -> dict:
    """
    Train and immediately save XGBoost anti-fake classifier.

    Args:
        X: feature matrix (n_samples × n_features)
        y: binary labels (1=fake/failure, 0=real/success)

    Returns:
        metrics dict with auc, accuracy, train_samples, test_samples
    """
    artifact, metrics = train_model(X, y)
    save_artifact(artifact)
    return metrics
