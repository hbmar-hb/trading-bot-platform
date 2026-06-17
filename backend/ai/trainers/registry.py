"""
Trainer Registry — factory for model trainers.

Allows swapping XGBoost → LightGBM → TabNet without changing pipeline code.
"""
from __future__ import annotations

from ai.trainers.base import ModelTrainer
from ai.trainers.xgboost_trainer import XGBoostTrainer

_TRAINERS: dict[str, type[ModelTrainer]] = {
    "xgboost": XGBoostTrainer,
}


def register_trainer(name: str, trainer_cls: type[ModelTrainer]) -> None:
    """Register a new trainer implementation."""
    _TRAINERS[name] = trainer_cls


def get_trainer(name: str = "xgboost") -> ModelTrainer:
    """Instantiate a trainer by name."""
    if name not in _TRAINERS:
        raise ValueError(f"Unknown trainer: {name}. Available: {list(_TRAINERS.keys())}")
    return _TRAINERS[name]()


def list_trainers() -> list[str]:
    """List available trainer names."""
    return list(_TRAINERS.keys())
