"""Walk-Forward Validation Engine for model retraining gate.

Time-series aware validation that prevents overfitting to recent regimes
and ensures the new model generalizes before deployment.

v3 — Fixed semantic data leakage:
  • WFV proxy now validates the ACTUAL anti-fake model target (FAILURE=1)
  • Classification metrics (AUC, precision, recall, F1) instead of trading metrics
  • Baseline comparison vs majority-class predictor
  • Optional y_returns for advisory trading metrics only
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
from loguru import logger


@dataclass(frozen=True)
class WFMetrics:
    """Metrics from a walk-forward validation run (classification-focused)."""

    # Classification metrics (primary gate criteria)
    auc: float
    accuracy: float
    precision: float
    recall: float
    f1: float
    logloss: float
    baseline_auc: float = 0.5
    auc_lift: float = 0.0

    # Advisory trading metrics (computed from y_returns if provided)
    sharpe: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    trades: int = 0
    avg_trade: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Gate thresholds (classification-focused) ─────────────────────────────
_MIN_AUC = 0.60                      # Must beat random by meaningful margin
_MIN_PRECISION = 0.45                # At least some true positives among predicted failures
_MIN_RECALL = 0.10                   # Catch at least 10% of failures
_MIN_F1 = 0.25                       # Balanced precision/recall floor
_MAX_LOGLOSS = 2.0                   # Not completely uncalibrated
_MIN_AUC_LIFT = 0.01                 # Must beat baseline by at least 1pp AUC

# Temporal stability thresholds
_MIN_FOLD_AUC = 0.58
_MAX_FOLD_AUC_STD = 0.07
_MIN_PER_FOLD_AUC = 0.55

# Relative retention vs old model (using AUC as primary metric)
_AUC_MIN_RETENTION = 0.90            # New AUC >= 90% of old
_PRECISION_MIN_RETENTION = 0.70      # New precision >= 70% of old

# Cap for unrealistic historical metrics from overfitted initial training
_AUC_HISTORY_CAP = 0.95


def _compute_trading_metrics(returns: list[float]) -> dict[str, float]:
    """Compute trading metrics from a list of per-trade returns (in %)."""
    n = len(returns)
    if n < 5:
        return {
            "sharpe": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "trades": n,
            "avg_trade": 0.0,
        }

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    win_rate = len(wins) / n
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    expectancy = sum(returns) / n

    mean_r = sum(returns) / n
    std_r = (sum((r - mean_r) ** 2 for r in returns) / n) ** 0.5
    sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in returns:
        cumulative += r
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    return {
        "sharpe": round(sharpe, 3),
        "profit_factor": round(profit_factor, 3),
        "expectancy": round(expectancy, 4),
        "win_rate": round(win_rate, 3),
        "max_drawdown": round(max_dd / 100, 4) if max_dd > 0 else 0.0,
        "trades": n,
        "avg_trade": round(mean_r, 4),
    }


def walk_forward_split(
    X: np.ndarray,
    y: np.ndarray,
    train_window: int = 60,
    test_window: int = 7,
    min_train_size: int = 30,
) -> list[tuple[int, int, int, int]]:
    """Generate time-series walk-forward split indices.

    Returns list of (train_start, train_end, test_start, test_end) tuples.
    """
    n = len(X)
    if n < min_train_size + test_window:
        raise ValueError(f"Insufficient data: {n} < {min_train_size + test_window}")

    splits = []
    start = 0
    while start + min_train_size + test_window <= n:
        train_end = start + train_window
        test_end = train_end + test_window
        if test_end > n:
            break

        splits.append((start, train_end, train_end, test_end))
        start += test_window  # Roll forward by test_window

    return splits


def evaluate_model(
    model,
    X_test: np.ndarray,
    y_test_binary: np.ndarray,
    y_test_returns: np.ndarray | None = None,
) -> WFMetrics:
    """Evaluate a trained model on a test set and return classification metrics.

    Args:
        model: Trained classifier with predict() and predict_proba().
        X_test: Feature matrix.
        y_test_binary: Binary labels (0=success, 1=failure).
        y_test_returns: Optional returns for advisory trading metrics.
    """
    from sklearn.metrics import (
        roc_auc_score, accuracy_score, precision_score, recall_score,
        f1_score, log_loss,
    )

    try:
        predictions = model.predict(X_test)
    except Exception as exc:
        logger.warning(f"[WF] Model prediction failed: {exc}")
        return WFMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 999.0)

    # Classification metrics
    if len(np.unique(y_test_binary)) < 2:
        # Only one class in test fold — can't compute meaningful metrics
        return WFMetrics(0.5, accuracy_score(y_test_binary, predictions), 0.0, 0.0, 0.0, 999.0)

    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X_test)[:, 1]
    else:
        proba = predictions.astype(float)

    try:
        auc = float(roc_auc_score(y_test_binary, proba))
    except Exception:
        auc = 0.5

    try:
        logloss = float(log_loss(y_test_binary, np.clip(proba, 1e-7, 1 - 1e-7)))
    except Exception:
        logloss = 999.0

    acc = float(accuracy_score(y_test_binary, predictions))
    prec = float(precision_score(y_test_binary, predictions, zero_division=0))
    rec = float(recall_score(y_test_binary, predictions, zero_division=0))
    f1 = float(f1_score(y_test_binary, predictions, zero_division=0))

    # Baseline: always predict majority class
    try:
        baseline_proba = np.full_like(proba, float(np.mean(y_test_binary)))
        baseline_auc = float(roc_auc_score(y_test_binary, baseline_proba))
    except Exception:
        baseline_auc = 0.5

    auc_lift = max(0.0, auc - baseline_auc)

    # Advisory trading metrics (only if returns provided)
    trading = {}
    if y_test_returns is not None:
        # "Take trade" = model predicts SUCCESS (0 = success in binary, so pred==0 means take)
        trade_mask = (predictions == 0)
        trade_returns = y_test_returns[trade_mask]
        trading = _compute_trading_metrics(trade_returns.tolist())

    return WFMetrics(
        auc=round(auc, 4),
        accuracy=round(acc, 4),
        precision=round(prec, 4),
        recall=round(rec, 4),
        f1=round(f1, 4),
        logloss=round(logloss, 4),
        baseline_auc=round(baseline_auc, 4),
        auc_lift=round(auc_lift, 4),
        sharpe=trading.get("sharpe", 0.0),
        profit_factor=trading.get("profit_factor", 0.0),
        expectancy=trading.get("expectancy", 0.0),
        win_rate=trading.get("win_rate", 0.0),
        max_drawdown=trading.get("max_drawdown", 0.0),
        trades=trading.get("trades", 0),
        avg_trade=trading.get("avg_trade", 0.0),
    )


def walk_forward_validate(
    model_class,
    X: np.ndarray,
    y_binary: np.ndarray,
    y_returns: np.ndarray | None = None,
    model_params: dict | None = None,
    train_window: int = 60,
    test_window: int = 7,
) -> dict[str, Any]:
    """Run walk-forward validation and return aggregated metrics.

    Args:
        model_class: Class with fit(X, y) and predict(X) methods.
        X: Feature matrix.
        y_binary: Binary labels (0=success, 1=failure) — same as anti-fake model.
        y_returns: Optional returns for advisory trading metrics.
        model_params: Constructor kwargs for model_class.
        train_window: Training window size in samples.
        test_window: Test window size in samples.

    Returns:
        Dict with aggregated metrics and per-fold results.
    """
    # Safety: enforce chronological order.
    # The dataset builder orders rows by resolved_at DESC (newest first).
    # Walk-forward must train on the oldest data and test on newer data, so
    # we reverse the array to ascending chronological order.
    chronological_sort = np.arange(len(X) - 1, -1, -1)
    X = X[chronological_sort]
    y_binary = y_binary[chronological_sort]
    if y_returns is not None:
        y_returns = y_returns[chronological_sort]

    split_indices = walk_forward_split(X, y_binary, train_window, test_window)
    if not split_indices:
        return {"error": "insufficient_data_for_splits"}

    # Detect and skip leading homogeneous zone (where only one class exists).
    # Historical datasets often have early samples where the minority class
    # resolution mechanism was not yet active. Skipping these upfront avoids
    # noisy "Fold skipped" warnings and yields more useful folds.
    minority_class = 0 if (y_binary == 0).sum() < (y_binary == 1).sum() else 1
    minority_indices = np.where(y_binary == minority_class)[0]
    if len(minority_indices) > 0:
        first_minority = int(minority_indices[0])
        # We want the first training window to include *both* classes.
        # Minimum training size is 30 (default). Start the first valid split
        # so that train_end >= first_minority + some buffer.
        start_offset = max(0, first_minority - train_window + 30)
        split_indices = [s for s in split_indices if s[0] >= start_offset]
        if not split_indices:
            # Fallback: keep at least the last few splits
            split_indices = walk_forward_split(X, y_binary, train_window, test_window)

    model_params = model_params or {}
    fold_metrics: list[WFMetrics] = []

    for i, (train_start, train_end, test_start, test_end) in enumerate(split_indices):
        try:
            X_train = X[train_start:train_end]
            y_train = y_binary[train_start:train_end]
            X_test = X[test_start:test_end]
            y_test = y_binary[test_start:test_end]

            # Skip folds where training labels have only one class
            if len(np.unique(y_train)) < 2:
                logger.warning(f"[WF] Fold {i + 1} skipped: only one class in training set")
                continue

            model = model_class(**model_params)
            model.fit(X_train, y_train)

            y_test_ret = y_returns[test_start:test_end] if y_returns is not None else None
            metrics = evaluate_model(model, X_test, y_test, y_test_ret)
            fold_metrics.append(metrics)
        except Exception as exc:
            logger.warning(f"[WF] Fold {i + 1} failed: {exc}")
            continue

    if not fold_metrics:
        return {"error": "all_folds_failed"}

    # Evaluación 2: temporal stability check
    fold_aucs = [m.auc for m in fold_metrics]
    stability = _check_temporal_stability(fold_aucs, fold_metrics)

    # Evaluación 3: target drift validation
    target_drift = None
    try:
        from ai.services.target_validator import TargetDriftValidator
        train_labels = y_binary[split_indices[0][0]:split_indices[0][1]] if split_indices else np.array([])
        test_labels = y_binary[split_indices[-1][2]:split_indices[-1][3]] if split_indices else np.array([])
        if len(train_labels) > 0 and len(test_labels) > 0:
            # validator expects 1=success, 0=failure; we have 0=success, 1=failure
            target_drift = TargetDriftValidator().validate(
                1 - train_labels,
                1 - test_labels,
            )
            if not target_drift.passes_gate:
                stability = {
                    "passes": False,
                    "reason": f"target_drift: {target_drift.reason}",
                    **stability,
                }
    except Exception:
        pass

    # Aggregate across folds
    n = len(fold_metrics)
    aggregated = WFMetrics(
        auc=round(sum(m.auc for m in fold_metrics) / n, 4),
        accuracy=round(sum(m.accuracy for m in fold_metrics) / n, 4),
        precision=round(sum(m.precision for m in fold_metrics) / n, 4),
        recall=round(sum(m.recall for m in fold_metrics) / n, 4),
        f1=round(sum(m.f1 for m in fold_metrics) / n, 4),
        logloss=round(sum(m.logloss for m in fold_metrics) / n, 4),
        baseline_auc=round(sum(m.baseline_auc for m in fold_metrics) / n, 4),
        auc_lift=round(sum(m.auc_lift for m in fold_metrics) / n, 4),
        sharpe=round(sum(m.sharpe for m in fold_metrics) / n, 3),
        profit_factor=round(sum(m.profit_factor for m in fold_metrics) / n, 3),
        expectancy=round(sum(m.expectancy for m in fold_metrics) / n, 4),
        win_rate=round(sum(m.win_rate for m in fold_metrics) / n, 3),
        max_drawdown=round(sum(m.max_drawdown for m in fold_metrics) / n, 4),
        trades=sum(m.trades for m in fold_metrics),
        avg_trade=round(sum(m.avg_trade for m in fold_metrics) / n, 4),
    )

    passes_gate = _passes_absolute_gate(aggregated) and stability["passes"]

    return {
        "folds": len(fold_metrics),
        "aggregated": aggregated.to_dict(),
        "fold_results": [m.to_dict() for m in fold_metrics],
        "passes_gate": passes_gate,
        "stability": stability,
    }


def _passes_absolute_gate(metrics: WFMetrics) -> bool:
    """Check if metrics pass absolute minimum thresholds (classification-focused)."""
    return (
        metrics.auc >= _MIN_AUC
        and metrics.precision >= _MIN_PRECISION
        and metrics.recall >= _MIN_RECALL
        and metrics.f1 >= _MIN_F1
        and metrics.logloss <= _MAX_LOGLOSS
        and metrics.auc_lift >= _MIN_AUC_LIFT
    )


def _check_temporal_stability(fold_aucs: list[float], fold_metrics: list) -> dict:
    """Check temporal stability of walk-forward folds.

    Evaluación 2: A model that performs well on average but has catastrophic
    folds is unstable and should be rejected.
    """
    if not fold_aucs or len(fold_aucs) < 2:
        return {"passes": False, "reason": "insufficient_folds_for_stability", "min_auc": 0, "auc_std": 0}

    min_auc = min(fold_aucs)
    auc_std = float(np.std(fold_aucs)) if fold_aucs else 0.0

    reasons = []
    if min_auc < _MIN_FOLD_AUC:
        reasons.append(f"min_auc={min_auc:.3f} < {_MIN_FOLD_AUC}")
    if auc_std >= _MAX_FOLD_AUC_STD:
        reasons.append(f"auc_std={auc_std:.3f} >= {_MAX_FOLD_AUC_STD}")
    if any(a <= _MIN_PER_FOLD_AUC for a in fold_aucs):
        reasons.append(f"at_least_one_fold_catastrophic (auc <= {_MIN_PER_FOLD_AUC})")

    if reasons:
        return {
            "passes": False,
            "reason": "; ".join(reasons),
            "min_auc": round(min_auc, 4),
            "auc_std": round(auc_std, 4),
            "fold_aucs": [round(a, 4) for a in fold_aucs],
        }

    return {
        "passes": True,
        "reason": None,
        "min_auc": round(min_auc, 4),
        "auc_std": round(auc_std, 4),
        "fold_aucs": [round(a, 4) for a in fold_aucs],
    }


def should_accept_new_model(
    old_metrics: dict[str, float],
    new_metrics: dict[str, float],
    stability: dict | None = None,
) -> tuple[bool, str]:
    """Gate: should the new model replace the old one?

    Args:
        old_metrics: Dict with classification keys: auc, precision, recall, f1, accuracy.
                     Also supports legacy keys: sharpe, profit_factor, expectancy.
        new_metrics: Same format.
        stability: Optional temporal stability check result from walk_forward_validate.

    Returns:
        (accepted, reason)
    """
    # Evaluación 2: temporal stability gate
    if stability and not stability.get("passes", True):
        return False, f"temporal_stability_failed: {stability.get('reason', 'unknown')}"

    # Absolute gate on new model (classification metrics)
    wf_new = WFMetrics(**new_metrics)
    if not _passes_absolute_gate(wf_new):
        return (
            False,
            f"new_model_fails_absolute_gate: auc={wf_new.auc:.3f} "
            f"precision={wf_new.precision:.3f} recall={wf_new.recall:.3f} "
            f"f1={wf_new.f1:.3f} lift={wf_new.auc_lift:.3f}"
        )

    # Relative retention vs old model (AUC as primary metric)
    old_auc = old_metrics.get("auc", old_metrics.get("sharpe", 0.5))
    old_prec = old_metrics.get("precision", old_metrics.get("profit_factor", 0.0))

    new_auc = new_metrics.get("auc", new_metrics.get("sharpe", 0.0))
    new_prec = new_metrics.get("precision", new_metrics.get("profit_factor", 0.0))

    # Cap unrealistic historical AUC
    capped_old_auc = min(old_auc, _AUC_HISTORY_CAP)
    if new_auc < capped_old_auc * _AUC_MIN_RETENTION:
        return False, f"auc_retention: {new_auc:.3f} < {capped_old_auc * _AUC_MIN_RETENTION:.3f}"

    if old_prec > 0 and new_prec < old_prec * _PRECISION_MIN_RETENTION:
        return False, f"precision_retention: {new_prec:.3f} < {old_prec * _PRECISION_MIN_RETENTION:.3f}"

    return True, "passed_all_gates"


# Convenience: convert WFMetrics to dict for JSON serialization
def metrics_to_dict(metrics: WFMetrics) -> dict[str, Any]:
    return metrics.to_dict()
