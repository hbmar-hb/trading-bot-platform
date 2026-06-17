"""
Base class for model trainers.

Provides a uniform interface so we can swap XGBoost for LightGBM/TabNet
or ensemble them without changing the pipeline.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TrainResult:
    """Standardized output from any trainer."""
    model: Any  # the fitted model object
    metrics: dict  # test metrics (auc, accuracy, precision, recall, etc.)
    feature_importance: dict[str, float]
    artifact_path: Path | None
    training_samples: int
    features_used: list[str]


class ModelTrainer(ABC):
    """Abstract base for all model trainers."""

    name: str = "base"

    @abstractmethod
    def train(self, X, y, **kwargs) -> TrainResult:
        """Train and return standardized result."""
        ...

    @abstractmethod
    def save(self, model, path: Path) -> None:
        """Serialize model to disk."""
        ...

    @abstractmethod
    def load(self, path: Path) -> Any:
        """Deserialize model from disk."""
        ...

    @abstractmethod
    def predict_proba(self, model, X) -> list[float]:
        """Return probability of positive class (FAILURE)."""
        ...
