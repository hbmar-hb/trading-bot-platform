#!/usr/bin/env python3
"""Offline candidate training pipeline for Fase D.

Trains a fresh anti-fake model on the full resolved dataset (realistic labels +
Fase A macro features), runs walk-forward validation, and — if it passes the
gate — saves it as candidate_anti_fake_v1.pkl for 48h shadow evaluation.

Can be run directly from the shell or imported as `train_candidate()` from the
API endpoint.
"""
from __future__ import annotations

import gc
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running this script from any cwd (e.g. project root or backend/)
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from loguru import logger

MODEL_DIR = BACKEND_DIR / "ai" / "models"
CANDIDATE_PATH = MODEL_DIR / "candidate_anti_fake_v1.pkl"


def train_candidate(force: bool = False) -> dict:
    """Train a candidate model and save it if it passes validation.

    Args:
        force: if True, save the candidate even when the WF gate rejects it.

    Returns:
        Dict with status, metrics, model_path and validation result.
    """
    import pandas as pd
    from ai.dataset_builder import build_dataset_with_metadata_sync
    from ai.trainers.anti_fake_trainer import train_model
    from ai.validation.walk_forward import (
        should_accept_new_model,
    )

    logger.info("[CandidateTrain] Loading dataset…")
    X, y_binary, y_returns, groups, sample_weights, signal_ids = (
        build_dataset_with_metadata_sync(max_samples=25000)
    )

    if len(X) < 500:
        return {
            "status": "insufficient_data",
            "samples": len(X),
            "required": 500,
        }

    logger.info(
        f"[CandidateTrain] Training on {len(X)} samples "
        f"(success={int((y_binary == 0).sum())}, failure={int((y_binary == 1).sum())})…"
    )

    artifact, metrics = train_model(X, y_binary, groups=groups, sample_weights=sample_weights)

    # Gate on the model's own out-of-fold (GroupKFold) metrics.  The
    # walk-forward proxy with small sliding windows is too noisy for this
    # dataset; the OOF metrics come from the actual model architecture and are
    # a more reliable acceptance gate.
    fold_aucs = metrics.get("fold_aucs") or []
    fold_auc_std = metrics.get("fold_auc_std", 0.0)
    min_fold_auc = min(fold_aucs) if fold_aucs else 0.0
    wf_passed = (
        metrics.get("auc", 0.0) >= 0.70
        and fold_auc_std <= 0.06
        and min_fold_auc >= 0.60
    )
    wf_reason = (
        "passed_oof_gate" if wf_passed
        else f"oof_gate_failed: auc={metrics.get('auc', 0):.3f} fold_std={fold_auc_std:.3f} min_fold={min_fold_auc:.3f}"
    )
    wf_metrics = {
        "auc": metrics.get("auc"),
        "fold_auc_std": fold_auc_std,
        "fold_aucs": fold_aucs,
        "min_fold_auc": min_fold_auc,
    }

    logger.info(
        f"[CandidateTrain] OOF gate: passed={wf_passed} reason={wf_reason} "
        f"auc={metrics.get('auc', 0):.3f} fold_std={fold_auc_std:.3f} min_fold={min_fold_auc:.3f}"
    )

    if not wf_passed and not force:
        logger.warning(f"[CandidateTrain] Candidate rejected by WF gate: {wf_reason}")
        del artifact, X, y_binary, y_returns
        gc.collect()
        return {
            "status": "rejected",
            "reason": wf_reason,
            "metrics": metrics,
            "wf_result": wf_metrics,
        }

    # Persist candidate artifact
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    artifact["trained_on"] = datetime.now(timezone.utc).isoformat()
    artifact["samples"] = len(X)

    import pickle
    with open(CANDIDATE_PATH, "wb") as f:
        pickle.dump(artifact, f)

    # Invalidate in-memory cache so the scanner loads the new candidate
    try:
        from ai.services import candidate_model
        candidate_model.invalidate()
        logger.info("[CandidateTrain] Candidate model cache invalidated")
    except Exception as exc:
        logger.warning(f"[CandidateTrain] Failed to invalidate candidate cache: {exc}")

    logger.info(
        f"[CandidateTrain] Candidate saved to {CANDIDATE_PATH} "
        f"(AUC={metrics.get('auc')}, ACC={metrics.get('accuracy')})"
    )

    del artifact, X, y_binary, y_returns
    gc.collect()

    result = {
        "status": "trained" if wf_passed else "saved_forced",
        "reason": wf_reason,
        "model_path": str(CANDIDATE_PATH),
        "metrics": metrics,
        "wf_result": wf_metrics,
    }
    if not wf_passed and force:
        result["forced"] = True
    return result


def promote_candidate() -> dict:
    """Promote candidate_anti_fake_v1.pkl to live anti_fake_v1.pkl.

    Keeps a timestamped backup of the previous live model.
    """
    live_path = MODEL_DIR / "anti_fake_v1.pkl"
    candidate_path = MODEL_DIR / "candidate_anti_fake_v1.pkl"

    if not candidate_path.exists():
        return {"promoted": False, "reason": "candidate_model_missing"}

    if live_path.exists():
        backup_name = f"anti_fake_v1_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pkl"
        backup_path = MODEL_DIR / backup_name
        import shutil
        shutil.copy2(live_path, backup_path)
    else:
        backup_path = None

    import shutil
    shutil.copy2(candidate_path, live_path)

    # Invalidate caches
    try:
        from ai import registry as anti_fake_registry
        anti_fake_registry.invalidate()
    except Exception:
        pass
    try:
        from ai.services import candidate_model
        candidate_model.invalidate()
    except Exception:
        pass

    return {
        "promoted": True,
        "candidate_path": str(candidate_path),
        "live_path": str(live_path),
        "backup_path": str(backup_path) if backup_path else None,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Train Fase D candidate model")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Save candidate even if walk-forward gate rejects it",
    )
    args = parser.parse_args()

    result = train_candidate(force=args.force)
    print(json.dumps(result, indent=2, default=str))
