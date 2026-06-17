#!/usr/bin/env python3
"""Diagnóstico de data leakage en WFV proxy.

Analiza correlación entre features y target para identificar qué
feature(s) permiten predicción perfecta.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    print("=" * 70)
    print("DIAGNÓSTICO DE DATA LEAKAGE EN WFV PROXY")
    print("=" * 70)

    from ai.dataset_builder import build_dataset_with_metadata_sync

    X, y_binary, y_returns, groups, sample_weights, signal_ids = build_dataset_with_metadata_sync(
        max_samples=5000
    )

    print(f"\n[1] DISTRIBUCIÓN DE TARGETS")
    print(f"    Total muestras: {len(X)}")
    print(f"    y_binary (FAILURE=1): {y_binary.sum()} / {len(y_binary)} = {y_binary.mean():.1%}")
    print(f"    y_returns > 0: {(y_returns > 0).sum()} / {len(y_returns)} = {(y_returns > 0).mean():.1%}")
    print(f"    y_returns mean: {y_returns.mean():.3f}")
    print(f"    y_returns std: {y_returns.std():.3f}")
    print(f"    y_returns min/max: {y_returns.min():.3f} / {y_returns.max():.3f}")

    print(f"\n[2] CORRELACIÓN FEATURES vs y_returns")
    correlations = []
    for col in X.columns:
        corr = X[col].corr(y_returns)
        if pd.notna(corr):
            correlations.append((col, abs(corr), corr))

    correlations.sort(key=lambda x: x[1], reverse=True)
    for col, abs_corr, corr in correlations[:15]:
        print(f"    {col:25s}: {corr:+.4f} (|{abs_corr:.4f}|)")

    print(f"\n[3] CORRELACIÓN FEATURES vs y_binary")
    correlations = []
    for col in X.columns:
        corr = X[col].corr(y_binary)
        if pd.notna(corr):
            correlations.append((col, abs(corr), corr))

    correlations.sort(key=lambda x: x[1], reverse=True)
    for col, abs_corr, corr in correlations[:15]:
        print(f"    {col:25s}: {corr:+.4f} (|{abs_corr:.4f}|)")

    print(f"\n[4] ANÁLISIS DE 'score' COMO PREDICTOR")
    score = X["score"]
    print(f"    score mean: {score.mean():.2f}")
    print(f"    score std: {score.std():.2f}")

    # Si score > umbral, cuál es el winrate?
    for th in [60, 70, 75, 80, 85]:
        mask = score >= th
        if mask.sum() > 0:
            wr = (y_returns[mask] > 0).mean()
            mean_ret = y_returns[mask].mean()
            print(f"    score >= {th}: n={mask.sum()}, winrate={wr:.1%}, avg_return={mean_ret:.3f}")

    print(f"\n[5] ANÁLISIS DE CAUSAL FEATURES")
    for col in ["avg_entry_slippage", "gap_frequency", "fee_rate", "tp_fill_rate"]:
        if col in X.columns:
            vals = X[col]
            print(f"    {col}: min={vals.min():.4f}, max={vals.max():.4f}, mean={vals.mean():.4f}")
            corr = vals.corr(y_returns)
            print(f"         corr(y_returns)={corr:.4f}")

    print(f"\n[6] ANÁLISIS DE is_real_trade")
    if "is_real_trade" in X.columns:
        for val in [0, 1]:
            mask = X["is_real_trade"] == val
            if mask.sum() > 0:
                wr = (y_returns[mask] > 0).mean()
                mean_ret = y_returns[mask].mean()
                print(f"    is_real_trade={val}: n={mask.sum()}, winrate={wr:.1%}, avg_return={mean_ret:.3f}")

    print(f"\n[7] PRUEBA WFV CON/SIN FEATURES SOSPECHOSAS")
    import numpy as np
    from ai.validation.walk_forward import walk_forward_validate
    from xgboost import XGBClassifier

    # WFV con todas las features (v3: binary target)
    n_success = int((y_binary == 0).sum())
    n_failure = int((y_binary == 1).sum())
    wf_spw = float(n_success / max(n_failure, 1))
    wf_all = walk_forward_validate(
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

    print(f"    Con TODAS las features:")
    if "error" not in wf_all:
        agg = wf_all["aggregated"]
        print(f"      AUC={agg.get('auc', 0):.3f} PR={agg.get('precision', 0):.3f} RC={agg.get('recall', 0):.3f} F1={agg.get('f1', 0):.3f} LIFT={agg.get('auc_lift', 0):.3f}")
        print(f"      Advisory: Sharpe={agg.get('sharpe', 0):.2f} PF={agg.get('profit_factor', 0):.2f} WR={agg.get('win_rate', 0):.1%} Trades={agg.get('trades', 0)}")
    else:
        print(f"      ERROR: {wf_all['error']}")

    # WFV SIN 'score'
    X_no_score = X.drop(columns=["score"])
    wf_no_score = walk_forward_validate(
        model_class=XGBClassifier,
        X=X_no_score.values,
        y_binary=y_binary.values,
        y_returns=y_returns.values,
        model_params={
            "n_estimators": 500, "max_depth": 3, "learning_rate": 0.05,
            "subsample": 0.7, "colsample_bytree": 0.7, "colsample_bylevel": 0.7,
            "reg_alpha": 0.5, "reg_lambda": 3.0, "gamma": 2.0,
            "min_child_weight": 10, "scale_pos_weight": wf_spw,
            "random_state": 42, "eval_metric": "logloss", "verbosity": 0,
        },
        train_window=max(60, len(X_no_score) // 10),
        test_window=max(20, len(X_no_score) // 25),
    )

    print(f"    SIN 'score':")
    if "error" not in wf_no_score:
        agg = wf_no_score["aggregated"]
        print(f"      AUC={agg.get('auc', 0):.3f} PR={agg.get('precision', 0):.3f} RC={agg.get('recall', 0):.3f} F1={agg.get('f1', 0):.3f} LIFT={agg.get('auc_lift', 0):.3f}")
        print(f"      Advisory: Sharpe={agg.get('sharpe', 0):.2f} PF={agg.get('profit_factor', 0):.2f} WR={agg.get('win_rate', 0):.1%} Trades={agg.get('trades', 0)}")
    else:
        print(f"      ERROR: {wf_no_score['error']}")

    # WFV solo con features de mercado (sin score, sin causal, sin is_real_trade)
    market_cols = [c for c in X.columns if c not in ["score", "is_real_trade", "avg_entry_slippage", "gap_frequency", "fee_rate", "tp_fill_rate"]]
    X_market = X[market_cols]
    wf_market = walk_forward_validate(
        model_class=XGBClassifier,
        X=X_market.values,
        y_binary=y_binary.values,
        y_returns=y_returns.values,
        model_params={
            "n_estimators": 500, "max_depth": 3, "learning_rate": 0.05,
            "subsample": 0.7, "colsample_bytree": 0.7, "colsample_bylevel": 0.7,
            "reg_alpha": 0.5, "reg_lambda": 3.0, "gamma": 2.0,
            "min_child_weight": 10, "scale_pos_weight": wf_spw,
            "random_state": 42, "eval_metric": "logloss", "verbosity": 0,
        },
        train_window=max(60, len(X_market) // 10),
        test_window=max(20, len(X_market) // 25),
    )

    print(f"    Solo MARKET STRUCTURE (sin score/causal/real):")
    if "error" not in wf_market:
        agg = wf_market["aggregated"]
        print(f"      AUC={agg.get('auc', 0):.3f} PR={agg.get('precision', 0):.3f} RC={agg.get('recall', 0):.3f} F1={agg.get('f1', 0):.3f} LIFT={agg.get('auc_lift', 0):.3f}")
        print(f"      Advisory: Sharpe={agg.get('sharpe', 0):.2f} PF={agg.get('profit_factor', 0):.2f} WR={agg.get('win_rate', 0):.1%} Trades={agg.get('trades', 0)}")
    else:
        print(f"      ERROR: {wf_market['error']}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    import pandas as pd
    main()
