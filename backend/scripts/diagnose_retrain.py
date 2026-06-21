#!/usr/bin/env python3
"""Diagnóstico del pipeline de retrain — ejecutar manualmente.

Uso:
    cd backend && python scripts/diagnose_retrain.py

Este script simula el pipeline completo de retrain sin guardar nada,
reportando en cada paso qué falla y por qué.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Añadir backend/ al path
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    print("=" * 70)
    print("DIAGNÓSTICO DE RETRAIN PIPELINE")
    print("=" * 70)

    # ── 1. Meta actual ──────────────────────────────────────────────
    meta_path = Path(__file__).parent.parent / "ai" / "models" / "retrain_meta.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        last = meta.get("last_trained_at", "NUNCA")
        samples = meta.get("samples_at_training", 0)
        hours_ago = (
            (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
            if last != "NUNCA" else float("inf")
        )
        print(f"\n[1] META ACTUAL")
        print(f"    Último retrain: {last} ({hours_ago:.1f}h atrás)")
        print(f"    Muestras entonces: {samples}")
        print(f"    fold_auc_std: {meta.get('fold_auc_std')}")
        print(f"    fold_aucs: {meta.get('fold_aucs')}")
        print(f"    wf_trades: {meta.get('wf_trades')}")
        print(f"    wf_reset_reason: {meta.get('_wf_reset_reason', 'N/A')}")
    else:
        print("\n[1] NO HAY META — esto sería first_training")

    # ── 2. Dataset builder ──────────────────────────────────────────
    print("\n[2] DATASET BUILDER")
    try:
        from ai.dataset_builder import build_dataset_with_metadata_sync

        X, y_binary, y_returns, groups, sample_weights, signal_ids = build_dataset_with_metadata_sync(
            max_samples=5000
        )
        print(f"    ✅ Dataset construido: {len(X)} muestras")
        print(f"    Features: {list(X.columns)}")
        print(f"    Groups únicos: {groups.nunique() if groups is not None else 'N/A'}")
        print(f"    Positivos (FAILURE): {y_binary.sum()} / {len(y_binary)}")
        print(f"    Win returns (>0): {(y_returns > 0).sum()} / {len(y_returns)}")

        if len(X) < 200:
            print(f"    ⚠️  Muestras insuficientes para entrenar (< 200)")
            return
    except Exception as exc:
        print(f"    ❌ Dataset builder FALLÓ: {exc}")
        import traceback
        traceback.print_exc()
        return

    # ── 3. Should retrain? ──────────────────────────────────────────
    print("\n[3] ¿DEBERÍA RETRAIN?")
    last_samples = meta.get("samples_at_training", 0)
    new_samples = len(X) - last_samples
    hours_since = (
        (datetime.now(timezone.utc) - datetime.fromisoformat(meta["last_trained_at"])).total_seconds() / 3600
        if meta.get("last_trained_at") else float("inf")
    )
    print(f"    Nuevas muestras: {new_samples} (requeridas: 50)")
    print(f"    Horas desde último: {hours_since:.1f}h (requeridas: 24)")
    should = hours_since >= 24 or new_samples >= 50
    print(f"    → {'SÍ debería retrain' if should else 'NO debería retrain aún'}")

    # ── 4. Anti-fake trainer ────────────────────────────────────────
    print("\n[4] ANTI-FAKE TRAINER (sin guardar)")
    try:
        from ai.trainers.anti_fake_trainer import train_model

        artifact, metrics = train_model(X, y_binary, groups=groups, sample_weights=sample_weights)
        print(f"    ✅ Entrenamiento OK")
        print(f"    OOF AUC: {metrics['oof_auc']}")
        print(f"    fold_auc_std: {metrics['fold_auc_std']}")
        print(f"    fold_aucs: {metrics['fold_aucs']}")
    except Exception as exc:
        print(f"    ❌ Entrenamiento FALLÓ: {exc}")
        import traceback
        traceback.print_exc()
        return

    # ── 5. WFV Proxy ────────────────────────────────────────────────
    print("\n[5] WALK-FORWARD VALIDATION PROXY")
    try:
        from ai.validation.walk_forward import walk_forward_validate
        from xgboost import XGBClassifier

        n_success = int((y_binary == 0).sum())
        n_failure = int((y_binary == 1).sum())
        wf_spw = float(n_success / max(n_failure, 1))
        wf_result = walk_forward_validate(
            model_class=XGBClassifier,
            X=X.values,
            y_binary=y_binary.values,
            y_returns=y_returns.values,
            model_params={
                "n_estimators": 500,
                "max_depth": 3,
                "learning_rate": 0.05,
                "subsample": 0.7,
                "colsample_bytree": 0.7,
                "colsample_bylevel": 0.7,
                "reg_alpha": 0.5,
                "reg_lambda": 3.0,
                "gamma": 2.0,
                "min_child_weight": 10,
                "scale_pos_weight": wf_spw,
                "random_state": 42,
                "eval_metric": "logloss",
                "verbosity": 0,
            },
            train_window=max(60, len(X) // 10),
            test_window=max(20, len(X) // 25),
        )

        if "error" in wf_result:
            print(f"    ⚠️  WFV proxy retornó error: {wf_result['error']}")
        else:
            agg = wf_result["aggregated"]
            print(f"    ✅ WFV proxy OK")
            print(f"    Folds: {wf_result['folds']}")
            print(f"    AUC: {agg.get('auc')}")
            print(f"    Precision: {agg.get('precision')}")
            print(f"    Recall: {agg.get('recall')}")
            print(f"    F1: {agg.get('f1')}")
            print(f"    AUC Lift: {agg.get('auc_lift')}")
            print(f"    Advisory Sharpe: {agg.get('sharpe')}")
            print(f"    Advisory PF: {agg.get('profit_factor')}")
            print(f"    Stability passes: {wf_result['stability']['passes']}")
            print(f"    Stability reason: {wf_result['stability'].get('reason', 'N/A')}")
    except Exception as exc:
        print(f"    ❌ WFV proxy FALLÓ: {exc}")
        import traceback
        traceback.print_exc()
        return

    # ── 6. WFV Gate (should_accept_new_model) ───────────────────────
    print("\n[6] WFV GATE (should_accept_new_model)")
    try:
        from ai.validation.walk_forward import _check_temporal_stability, should_accept_new_model

        model_fold_aucs = metrics.get("fold_aucs") or []
        model_stability = (
            _check_temporal_stability(model_fold_aucs, [])
            if len(model_fold_aucs) >= 2 else None
        )

        old_metrics = {
            "auc": meta.get("wf_auc", meta.get("wf_sharpe", 0.55)),
            "precision": meta.get("wf_precision", 0.30),
            "recall": meta.get("wf_recall", 0.30),
            "f1": meta.get("wf_f1", 0.25),
            "sharpe": meta.get("wf_sharpe", 0.5),
            "profit_factor": meta.get("wf_profit_factor", 1.1),
            "expectancy": meta.get("wf_expectancy", 0.1),
            "win_rate": meta.get("wf_win_rate", 0.35),
            "max_drawdown": meta.get("wf_max_drawdown", 0.25),
        }

        if "error" in wf_result:
            print(f"    ⚠️  WFV proxy falló → gate NO bloquea (graceful degradation)")
            wf_passed = True
            wf_reason = f"wf_error:{wf_result['error']}"
        else:
            wf_metrics = wf_result["aggregated"]
            wf_stability = wf_result.get("stability")
            wf_passed, wf_reason = should_accept_new_model(old_metrics, wf_metrics, model_stability)

        print(f"    Gate result: {'✅ PASSED' if wf_passed else '❌ REJECTED'}")
        print(f"    Reason: {wf_reason}")
        if model_stability:
            print(f"    Model stability: min_auc={model_stability.get('min_auc')} std={model_stability.get('auc_std')}")
    except Exception as exc:
        print(f"    ❌ WFV Gate FALLÓ: {exc}")
        import traceback
        traceback.print_exc()
        return

    # ── 7. Resumen ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)
    if should and wf_passed:
        print("✅ El retrain DEBERÍA ejecutarse y PASAR el gate.")
        print("   Si no se ejecuta, el problema está en Celery (beat/worker no corriendo).")
    elif should and not wf_passed:
        print("⚠️  El retrain debería ejecutarse pero el WFV Gate lo RECHAZARÍA.")
        print("   Revisa el reason arriba para entender por qué.")
    else:
        print("ℹ️  El retrain NO debería ejecutarse todavía (insuficientes muestras/tiempo).")


if __name__ == "__main__":
    main()
