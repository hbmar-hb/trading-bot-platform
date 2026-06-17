"""
XGBoost trainer implementing the ModelTrainer interface.

This wraps the existing anti_fake_trainer logic into the standard interface
so it can be used interchangeably with future trainers (LightGBM, TabNet).
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from ai.trainers.base import ModelTrainer, TrainResult


class XGBoostTrainer(ModelTrainer):
    """XGBoost binary classifier for anti-fake prediction."""

    name = "xgboost"

    def train(
        self,
        X,
        y,
        test_size: float = 0.2,
        random_state: int = 42,
        **kwargs,
    ) -> TrainResult:
        """Train XGBoost and return standardized result."""
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )

        model = XGBClassifier(
            n_estimators=kwargs.get("n_estimators", 200),
            max_depth=kwargs.get("max_depth", 4),
            learning_rate=kwargs.get("learning_rate", 0.05),
            subsample=kwargs.get("subsample", 0.8),
            colsample_bytree=kwargs.get("colsample_bytree", 0.8),
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=random_state,
        )
        model.fit(X_train, y_train)

        # Metrics
        from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score
        y_prob = model.predict_proba(X_test)[:, 1]
        y_pred = model.predict(X_test)

        metrics = {
            "auc": round(float(roc_auc_score(y_test, y_prob)), 4),
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        }

        # Feature importance
        importance = model.get_booster().get_score(importance_type="gain")
        total = sum(importance.values()) or 1.0
        fi = {k: round(v / total, 4) for k, v in importance.items()}

        return TrainResult(
            model=model,
            metrics=metrics,
            feature_importance=fi,
            artifact_path=None,
            training_samples=len(X_train),
            features_used=list(X.columns),
        )

    def save(self, model, path: Path) -> None:
        """Save model as pickle."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(model, f)

    def load(self, path: Path) -> Any:
        """Load model from pickle."""
        with open(path, "rb") as f:
            return pickle.load(f)

    def predict_proba(self, model, X) -> list[float]:
        """Return failure probability."""
        probs = model.predict_proba(X)
        return probs[:, 1].tolist()
