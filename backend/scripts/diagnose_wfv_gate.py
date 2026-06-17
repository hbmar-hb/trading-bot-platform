#!/usr/bin/env python3
"""Diagnóstico profundo del WFV Gate (v3).

Analiza fold por fold, baseline comparison, target drift,
y verifica que el gate use el modelo real (model_stability) como primario.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    print("=" * 70)
    print("DIAGNÓSTICO PROFUNDO DEL WFV GATE (v3)")
    print("=" * 70)

    from ai.dataset_builder import build_dataset_with_metadata_sync
    from ai.trainers.anti_fake_trainer import train_model
    from ai.validation.walk_forward import (
        walk_forward_validate, should_accept_new_model, _check_temporal_stability
    )
    from xgboost import XGBClassifier
    import numpy as np

    X, y_binary, y_returns, groups, sample_weights, signal_ids = (
        build_dataset_with_metadata_sync(max_samples=5000)
    )

    print(f"\n[1] DATASET OVERVIEW")
    print(f"    Samples: {len(X)}")
    print(f"    Features: {len(X.columns)}")
    print(f"    FAILURE rate: {y_binary.mean():.1%} ({y_binary.sum()} / {len(y_binary)})")
    print(f"    SUCCESS rate: {(1-y_binary).mean():.1%} ({(y_binary==0).sum()} / {len(y_binary)})")
    print(f"    Groups: {groups.nunique()}")

    # Chronological target distribution
    print(f"\n[2] TARGET DISTRIBUCIÓN CRONOLÓGICA")
    n = len(y_binary)
    bins = 10
    for i in range(bins):
        start = i * n // bins
        end = (i + 1) * n // bins
        y_slice = y_binary.values[start:end]
        print(f"    Bin {i+1:2d} ({start:5d}-{end:5d}): FAILURE={y_slice.mean():.1%} n={len(y_slice)}")

    # Anti-fake trainer (real gate)
    print(f"\n[3] ANTI-FAKE TRAINER (Gate Principal)")
    artifact, metrics = train_model(X, y_binary, groups=groups, sample_weights=sample_weights)
    print(f"    OOF AUC: {metrics['oof_auc']}")
    print(f"    OOF Accuracy: {metrics['oof_accuracy']}")
    print(f"    fold_auc_std: {metrics['fold_auc_std']}")
    print(f"    fold_aucs: {metrics['fold_aucs']}")

    model_stability = _check_temporal_stability(metrics.get("fold_aucs") or [], [])
    print(f"    model_stability: passes={model_stability['passes']}")
    print(f"      min_auc={model_stability.get('min_auc')} std={model_stability.get('auc_std')}")
    if model_stability.get('reason'):
        print(f"      reason: {model_stability['reason']}")

    # WFV Proxy (advisory)
    print(f"\n[4] WFV PROXY (Advisory)")
    n_success = int((y_binary == 0).sum())
    n_failure = int((y_binary == 1).sum())
    wf_spw = float(n_success / max(n_failure, 1))
    print(f"    scale_pos_weight: {wf_spw:.2f} (SUCCESS/FAILURE)")

    wf_result = walk_forward_validate(
        model_class=XGBClassifier,
        X=X.values,
        y_binary=y_binary.values,
        y_returns=y_returns.values,
        model_params={
            "n_estimators": 500, "max_depth": 3, "learning_rate": 0.05,
            "subsample": 0.7, "colsample_bytree": 0.7, "colsample_bylevel": 0.7,
            "reg_alpha": 0.5, "reg_lambda": 3.0, "gamma": 2.0,
            "min_child_weight": 10, "scale_pos_weight": wf_spw,
            "random_state": 42, "eval_metric": "logloss", "verbosity": 0,
        },
        train_window=max(60, len(X) // 10),
        test_window=max(20, len(X) // 25),
    )

    if "error" in wf_result:
        print(f"    ERROR: {wf_result['error']}")
        return

    print(f"    Total folds attempted: ~{len(X) // max(20, len(X) // 25)}")
    print(f"    Folds executed: {wf_result['folds']}")
    print(f"    Folds skipped: ~{len(X) // max(20, len(X) // 25) - wf_result['folds']}")

    print(f"\n    [4a] Métricas de Clasificación (Gate v3)")
    agg = wf_result["aggregated"]
    print(f"      AUC:        {agg.get('auc', 0):.4f}  (min={_MIN_AUC})")
    print(f"      Precision:  {agg.get('precision', 0):.4f}  (min={_MIN_PRECISION})")
    print(f"      Recall:     {agg.get('recall', 0):.4f}  (min={_MIN_RECALL})")
    print(f"      F1:         {agg.get('f1', 0):.4f}  (min={_MIN_F1})")
    print(f"      LogLoss:    {agg.get('logloss', 0):.4f}  (max={_MAX_LOGLOSS})")
    print(f"      AUC Lift:   {agg.get('auc_lift', 0):.4f}  (min={_MIN_AUC_LIFT})")
    print(f"      Baseline:   {agg.get('baseline_auc', 0):.4f}")

    print(f"\n    [4b] Métricas de Trading (Advisory ONLY)")
    print(f"      Sharpe:     {agg.get('sharpe', 0):.2f}")
    print(f"      PF:         {agg.get('profit_factor', 0):.2f}")
    print(f"      WR:         {agg.get('win_rate', 0):.1%}")
    print(f"      Trades:     {agg.get('trades', 0)}")
    print(f"      Expectancy: {agg.get('expectancy', 0):.4f}")

    print(f"\n    [4c] Per-Fold Results")
    for i, fold in enumerate(wf_result.get("fold_results", [])):
        print(f"      Fold {i+1}: AUC={fold.get('auc', 0):.3f} PR={fold.get('precision', 0):.3f} "
              f"RC={fold.get('recall', 0):.3f} F1={fold.get('f1', 0):.3f} "
              f"trades={fold.get('trades', 0)}")

    wf_stability = wf_result.get("stability", {})
    print(f"\n    [4d] Proxy Stability (Advisory)")
    print(f"      passes: {wf_stability.get('passes')}")
    print(f"      min_auc: {wf_stability.get('min_auc')} std: {wf_stability.get('auc_std')}")
    if wf_stability.get('reason'):
        print(f"      reason: {wf_stability['reason']}")

    # Gate evaluation
    print(f"\n[5] GATE EVALUATION")
    old_metrics = {
        "auc": 0.55, "precision": 0.30, "recall": 0.30, "f1": 0.25,
    }
    passed, reason = should_accept_new_model(old_metrics, agg, model_stability)
    print(f"    old_metrics (simulated first-run): {old_metrics}")
    print(f"    new_metrics: auc={agg.get('auc',0):.3f} pr={agg.get('precision',0):.3f}")
    print(f"    Gate result: {'✅ PASSED' if passed else '❌ REJECTED'}")
    print(f"    Reason: {reason}")

    # Absolute gate check
    from ai.validation.walk_forward import _passes_absolute_gate, WFMetrics
    abs_pass = _passes_absolute_gate(WFMetrics(**agg))
    print(f"    Absolute gate: {'✅ PASSED' if abs_pass else '❌ FAILED'}")

    print(f"\n[6] LEAKAGE ASSESSMENT")
    print(f"    Dataset bias (natural): {(y_returns > 0).mean():.1%} positive returns")
    print(f"    'Buy everything' PF: {abs(y_returns[y_returns > 0].sum() / y_returns[y_returns <= 0].abs().sum()):.2f}")
    print(f"    Proxy AUC Lift: {agg.get('auc_lift', 0):.4f}")
    if agg.get('auc_lift', 0) > 0.05:
        print(f"    ✅ AUC Lift > 0.05 → modelo tiene edge real sobre baseline")
    else:
        print(f"    ⚠️  AUC Lift ≤ 0.05 → modelo apenas mejora baseline")

    # Feature importance from trained model
    print(f"\n[7] FEATURE IMPORTANCE (Anti-Fake Model)")
    fi = metrics.get("feature_importance", {})
    for feat, imp in sorted(fi.items(), key=lambda x: -x[1])[:10]:
        print(f"    {feat:25s}: {imp:.4f}")

    print(f"\n{'='*70}")
    print("CONCLUSIÓN")
    print(f"{'='*70}")
    if passed and model_stability.get("passes"):
        print("✅ Gate PASA con modelo real (model_stability) como primario.")
        print("   El proxy es advisory y su alta varianza es esperada con ventanas")
        print("   deslizantes pequeñas en dataset desbalanceado.")
    else:
        print("❌ Gate FALLA. Revisar reason arriba.")


if __name__ == "__main__":
    from ai.validation.walk_forward import (
        _MIN_AUC, _MIN_PRECISION, _MIN_RECALL, _MIN_F1,
        _MAX_LOGLOSS, _MIN_AUC_LIFT,
    )
    main()
