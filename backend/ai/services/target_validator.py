"""Target Drift Validator — detects systemic market changes.

Evaluación 3: Detect when the target becomes impossible to predict
(e.g. 95% FAILURE due to systemic crash, or >20% shift vs training).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from loguru import logger


@dataclass(frozen=True)
class TargetDriftResult:
    passes_gate: bool
    reason: str | None
    train_success_rate: float
    val_success_rate: float
    recommendation: Literal["DEPLOY", "REJECT_MARKET_ANOMALY", "REJECT_RETRAIN_NEEDED"]


class TargetDriftValidator:
    """Validate that train and validation targets are compatible.

    Usage:
        validator = TargetDriftValidator()
        result = validator.validate(y_train, y_val)
        if not result.passes_gate:
            abort_training(result.recommendation)
    """

    def validate(self, y_train: np.ndarray, y_val: np.ndarray) -> TargetDriftResult:
        """Check for target drift between training and validation sets.

        Args:
            y_train: Binary labels (0=success, 1=failure) from training set
            y_val: Binary labels from validation set

        Returns:
            TargetDriftResult with pass/fail and recommendation.
        """
        if len(y_train) == 0 or len(y_val) == 0:
            return TargetDriftResult(
                passes_gate=False,
                reason="empty_set",
                train_success_rate=0.0,
                val_success_rate=0.0,
                recommendation="REJECT_RETRAIN_NEEDED",
            )

        train_success_rate = float(np.mean(y_train == 0))
        val_success_rate = float(np.mean(y_val == 0))

        # Check 1: Market anomaly (extreme success rate)
        if val_success_rate < 0.15 or val_success_rate > 0.85:
            logger.warning(
                f"[TargetDrift] MARKET ANOMALY detected: "
                f"val_success_rate={val_success_rate:.1%} "
                f"(train={train_success_rate:.1%})"
            )
            return TargetDriftResult(
                passes_gate=False,
                reason=f"market_anomaly: val_success_rate={val_success_rate:.1%}",
                train_success_rate=round(train_success_rate, 4),
                val_success_rate=round(val_success_rate, 4),
                recommendation="REJECT_MARKET_ANOMALY",
            )

        # Check 2: Target shift (>20% difference vs training)
        if abs(val_success_rate - train_success_rate) > 0.20:
            logger.warning(
                f"[TargetDrift] TARGET SHIFT detected: "
                f"train={train_success_rate:.1%} val={val_success_rate:.1%} "
                f"diff={abs(val_success_rate - train_success_rate):.1%}"
            )
            return TargetDriftResult(
                passes_gate=False,
                reason=f"target_shift: |{val_success_rate:.1%} - {train_success_rate:.1%}| > 20%",
                train_success_rate=round(train_success_rate, 4),
                val_success_rate=round(val_success_rate, 4),
                recommendation="REJECT_RETRAIN_NEEDED",
            )

        return TargetDriftResult(
            passes_gate=True,
            reason=None,
            train_success_rate=round(train_success_rate, 4),
            val_success_rate=round(val_success_rate, 4),
            recommendation="DEPLOY",
        )


def validate_target_drift(y_train: np.ndarray, y_val: np.ndarray) -> dict:
    """Convenience function returning a plain dict."""
    result = TargetDriftValidator().validate(y_train, y_val)
    return {
        "passes_gate": result.passes_gate,
        "reason": result.reason,
        "train_success_rate": result.train_success_rate,
        "val_success_rate": result.val_success_rate,
        "recommendation": result.recommendation,
    }
