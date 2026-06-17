"""XGBoost Anti-Fake retraining task.

Triggered by Celery Beat every 6 hours.
Retrains when:
  - ≥24h since last training, OR
  - ≥50 new resolved signals since last training

Also callable manually via POST /ai/model/train.
Skips silently if fewer than 200 resolved signals exist.
"""
import gc
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from celery import shared_task
from loguru import logger

# Use same directory as anti_fake_trainer MODEL_DIR so meta is persisted correctly
META_PATH = Path(__file__).parent.parent.parent / "ai" / "models" / "retrain_meta.json"
MIN_SAMPLES = 200
MIN_HOURS = 24
MIN_NEW_SAMPLES = 50


def _load_meta() -> dict:
    if META_PATH.exists():
        try:
            return json.loads(META_PATH.read_text())
        except Exception:
            pass
    return {}


def _to_json_safe(obj):
    """Recursively convert numpy scalars / arrays to Python natives."""
    import numpy as np
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(v) for v in obj]
    return obj


def _save_meta(meta: dict) -> None:
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(_to_json_safe(meta), indent=2))


ADAPTIVE_WEIGHTS_PATH = Path(__file__).parent.parent.parent / "ai" / "models" / "adaptive_weights.json"

# V2.1 Base weights (rebalanced pillars)
_BASE_WEIGHTS = {
    "structure_CHoCH": 20.0,
    "structure_BOS":   12.0,
    "trigger_OB":      12.0,
    "trigger_FVG":      8.0,
    "fvg_context":      0.0,  # removed from score base (noise without displacement)
    "sweep":           25.0,  # liquidity is primary engine
    "pd_array":        15.0,
    "htf_bias":        20.0,  # new: HTF alignment pillar
    "killzone":         0.0,  # moved to timing_multiplier feature
    "eq_obstacle":      8.0,
}

# Feature → component mapping
_FEATURE_MAP = {
    "ob_distance_atr":  ["trigger_OB"],
    "trigger_fvg":      ["trigger_FVG"],
    "trigger_ob":       ["trigger_OB"],
    "bias_bull":        ["structure_CHoCH", "structure_BOS"],
    "fvg_aligned_count":["fvg_context"],
    "sweep_bool":       ["sweep"],
    "pd_position":      ["pd_array"],
    "htf_aligned":      ["htf_bias"],
    "hour_utc":         ["killzone"],
    "day_of_week":      ["killzone"],
    "break_choch":      ["structure_CHoCH", "structure_BOS"],
    "eq_highs_count":   ["eq_obstacle"],
    "eq_lows_count":    ["eq_obstacle"],
    "score":            list(_BASE_WEIGHTS.keys()),  # global scaling
    "volume_ratio":     ["sweep", "structure_CHoCH", "structure_BOS"],
    "spread_atr":       ["trigger_OB", "trigger_FVG", "fvg_context"],
    # Execution-quality features affect all components (costs reduce edge universally)
    "avg_entry_slippage": list(_BASE_WEIGHTS.keys()),
    "gap_frequency":      list(_BASE_WEIGHTS.keys()),
    "fee_rate":           list(_BASE_WEIGHTS.keys()),
    "tp_fill_rate":       list(_BASE_WEIGHTS.keys()),
    "is_real_trade":      list(_BASE_WEIGHTS.keys()),
}


def _build_global_weights(feature_importance: dict) -> dict:
    """Normalize feature importance into global adaptive confluence weights.
    If feature_importance is empty, returns base weights unchanged."""
    if not feature_importance:
        return dict(_BASE_WEIGHTS)

    component_scores: dict[str, float] = {k: 0.0 for k in _BASE_WEIGHTS}
    for feat, importance in feature_importance.items():
        importance = float(importance)
        targets = _FEATURE_MAP.get(feat, [])
        if not targets:
            continue
        share = importance / len(targets)
        for t in targets:
            component_scores[t] += share

    max_score = max(component_scores.values()) if component_scores else 1.0
    if max_score <= 0:
        max_score = 1.0

    adaptive = {}
    for comp, base in _BASE_WEIGHTS.items():
        score = component_scores.get(comp, 0.0)
        factor = 0.5 + (score / max_score)
        factor = max(0.5, min(1.5, factor))
        adaptive[comp] = round(base * factor, 1)
    return adaptive


def _component_key(sig) -> dict[str, bool]:
    """Return which components are active for a signal (from features)."""
    f = sig.features or {}
    return {
        "structure_CHoCH": f.get("break_type") == "CHoCH",
        "structure_BOS":   f.get("break_type") == "BOS",
        "trigger_OB":      f.get("trigger") == "ob",
        "trigger_FVG":     f.get("trigger") == "fvg",
        "fvg_context":     f.get("fvg_aligned_count", 0) > 0,
        "sweep":           f.get("sweep_detected", False) is True,
        "pd_array":        (sig.direction == "long" and f.get("pd_position", 0.5) < 0.5) or
                           (sig.direction == "short" and f.get("pd_position", 0.5) > 0.5),
        "htf_bias":        f.get("htf_aligned") is True,
        "killzone":        f.get("killzone") is not None,
        "eq_obstacle":     f.get("eq_highs_count", 0) > 0 or f.get("eq_lows_count", 0) > 0,
    }


def _build_per_ticker_weights(db, global_weights: dict) -> dict:
    """Compute per-ticker/timeframe weight adjustments based on historical component performance.
    Returns {ticker: {timeframe: {component: weight}}}.

    Uses timeframe-aware data quality:
      - Real + same_tf = full weight (1.0)
      - Paper + same_tf = half weight (0.5)
      - Real + diff_tf = low weight (0.2)
      - Paper + diff_tf = excluded (0.0)

    This allows paper testing on long-term timeframes to contribute to
    weight calibration for those timeframes without polluting short-term.
    """
    from app.models.ai_signal import AISignal
    from app.models.position import Position
    from app.models.bot_config import BotConfig
    from sqlalchemy import func

    # Build signal quality map: signal_id -> (is_real, signal_timeframe)
    signal_meta = (
        db.query(
            Position.extra_config["ai_signal_id"].astext.label("signal_id"),
            BotConfig.paper_balance_id.is_(None).label("is_real"),
            AISignal.timeframe.label("signal_timeframe"),
        )
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .join(AISignal, AISignal.id == func.cast(Position.extra_config["ai_signal_id"].astext, AISignal.id.type))
        .filter(Position.extra_config["ai_signal_id"].isnot(None))
        .subquery()
    )

    # Get all resolved signals with features
    all_signals = (
        db.query(AISignal)
        .filter(AISignal.realistic_outcome.in_(["SUCCESS", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL", "CENSORED"]))
        .filter(AISignal.features.isnot(None))
        .all()
    )

    # Build meta lookup
    meta_rows = db.query(
        signal_meta.c.signal_id,
        signal_meta.c.is_real,
        signal_meta.c.signal_timeframe,
    ).all()
    meta_map = {r.signal_id: (r.is_real, r.signal_timeframe or "1h") for r in meta_rows}

    # Bucket by ticker/timeframe with quality weights
    buckets: dict = {}  # (ticker, tf) -> [(signal, weight), ...]
    for s in all_signals:
        sid = str(s.id)
        if sid in meta_map:
            is_real, sig_tf = meta_map[sid]
            # For per-ticker weights, we want SAME timeframe data
            # Paper same_tf gets 0.5 weight, real same_tf gets 1.0
            if s.timeframe == sig_tf:
                weight = 1.0 if is_real else 0.5
            else:
                weight = 0.2 if is_real else 0.0
        else:
            # No position found — pure backtest signal, very low weight
            weight = 0.1

        if weight <= 0:
            continue

        tf = s.timeframe or "unknown"
        key = (s.ticker.upper(), tf)
        if key not in buckets:
            buckets[key] = []
        buckets[key].append((s, weight))

    result: dict = {}
    MIN_WEIGHTED_SAMPLES = 15  # weighted samples needed

    for (ticker, tf), weighted_signals in buckets.items():
        total_weight = sum(w for _, w in weighted_signals)
        if total_weight < MIN_WEIGHTED_SAMPLES:
            continue

        # Calculate weighted win rate per component
        comp_stats: dict[str, dict] = {k: {"win_weight": 0.0, "total_weight": 0.0} for k in _BASE_WEIGHTS}
        global_win_weight = 0.0
        for s, weight in weighted_signals:
            active = _component_key(s)
            if s.realistic_outcome == "SUCCESS":
                is_win = True
                win_weight = weight
            elif s.realistic_outcome in ("FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL"):
                is_win = False
                win_weight = 0.0
            elif s.realistic_outcome == "CENSORED":
                is_win = None  # neutral
                win_weight = weight * 0.5
            else:
                is_win = False
                win_weight = 0.0
            global_win_weight += win_weight
            for comp, present in active.items():
                if present:
                    comp_stats[comp]["total_weight"] += weight
                    comp_stats[comp]["win_weight"] += win_weight

        global_wr = global_win_weight / total_weight if total_weight > 0 else 0

        adjusted = {}
        for comp, base in global_weights.items():
            stats = comp_stats[comp]
            if stats["total_weight"] < 3:
                adjusted[comp] = base
                continue
            comp_wr = stats["win_weight"] / stats["total_weight"]
            # Relative performance factor: 0.5x to 1.5x
            if global_wr > 0:
                rel = comp_wr / global_wr
            else:
                rel = 1.0
            factor = max(0.5, min(1.5, rel))
            adjusted[comp] = round(base * factor, 1)

        if ticker not in result:
            result[ticker] = {}
        result[ticker][tf] = adjusted
        logger.info(
            f"[RETRAIN] Adaptive weights for {ticker}/{tf}: {adjusted} "
            f"(weighted_n={total_weight:.1f}, global_wr={global_wr:.1%})"
        )

    return result


# Evaluación 2: rate-limit adaptive weight changes to prevent instability cascade
_MAX_WEIGHT_DELTA = 0.10  # ±10% maximum change per retrain


def _rate_limit_weights(new_weights: dict, old_weights: dict) -> dict:
    """Clamp each weight change to ±_MAX_WEIGHT_DELTA of its previous value."""
    clamped = {}
    for comp, new_val in new_weights.items():
        old_val = old_weights.get(comp, new_val)
        delta = max(-_MAX_WEIGHT_DELTA, min(_MAX_WEIGHT_DELTA, new_val - old_val))
        clamped[comp] = round(old_val + delta, 1)
    return clamped


def _load_current_adaptive_weights() -> dict:
    """Load previously saved adaptive weights (global only for rate limiting)."""
    if ADAPTIVE_WEIGHTS_PATH.exists():
        try:
            data = json.loads(ADAPTIVE_WEIGHTS_PATH.read_text())
            return data.get("global", {})
        except Exception:
            pass
    return {}


def _build_and_save_adaptive_weights(feature_importance: dict, db=None, bot_id: str | None = None) -> None:
    """Build global + per-ticker + per-bot adaptive weights and persist to JSON.

    Evaluación 2: weight changes are rate-limited to ±10% per retrain
    to prevent adaptive instability cascade.
    """
    raw_weights = _build_global_weights(feature_importance)

    # Load existing payload if any
    existing_payload = {}
    if ADAPTIVE_WEIGHTS_PATH.exists():
        try:
            existing_payload = json.loads(ADAPTIVE_WEIGHTS_PATH.read_text())
        except Exception:
            pass

    if bot_id is not None:
        # Per-bot update: rate-limit against previous bot weights or base weights
        old_bot = (existing_payload.get("by_bot", {}) or {}).get(bot_id, {})
        anchor = old_bot if old_bot else dict(_BASE_WEIGHTS)
        bot_weights = _rate_limit_weights(raw_weights, anchor)

        # Merge into existing payload without touching global/by_ticker
        payload = dict(existing_payload)
        payload.setdefault("by_bot", {})[bot_id] = bot_weights
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()

        ADAPTIVE_WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        ADAPTIVE_WEIGHTS_PATH.write_text(json.dumps(payload, indent=2))
        logger.info(
            f"[RETRAIN] Adaptive weights saved for bot {bot_id} "
            f"(rate-limited ±{_MAX_WEIGHT_DELTA:.0%})"
        )
        return

    # Global + per-ticker update
    current_global = _load_current_adaptive_weights()
    anchor = current_global if current_global else dict(_BASE_WEIGHTS)
    global_weights = _rate_limit_weights(raw_weights, anchor)

    per_ticker = {}
    if db is not None:
        try:
            raw_per_ticker = _build_per_ticker_weights(db, global_weights)
            # Rate-limit per-ticker weights against their previous values.
            # raw_per_ticker is {ticker: {tf: {comp: weight}}} — iterate two levels.
            old_per_ticker = existing_payload.get("by_ticker", {}) if existing_payload else {}
            for ticker, new_tweights in raw_per_ticker.items():
                old_ticker = old_per_ticker.get(ticker, {})
                per_ticker[ticker] = {}
                for tf, new_tf_weights in new_tweights.items():
                    old_tf_weights = old_ticker.get(tf, {}) if isinstance(old_ticker, dict) else {}
                    per_ticker[ticker][tf] = _rate_limit_weights(
                        new_tf_weights,
                        old_tf_weights if old_tf_weights else dict(_BASE_WEIGHTS),
                    )
        except Exception as e:
            logger.warning(f"[RETRAIN] Per-ticker weights failed: {e}")

    payload = {
        "global": global_weights,
        "by_ticker": per_ticker,
        "by_bot": existing_payload.get("by_bot", {}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    ADAPTIVE_WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ADAPTIVE_WEIGHTS_PATH.write_text(json.dumps(payload, indent=2))
    logger.info(f"[RETRAIN] Adaptive weights saved (rate-limited ±{_MAX_WEIGHT_DELTA:.0%}) — global + {len(per_ticker)} tickers")


def _should_retrain(current_samples: int) -> tuple[bool, str]:
    meta = _load_meta()
    last_trained = meta.get("last_trained_at")
    last_samples = meta.get("samples_at_training", 0)

    if not last_trained:
        return True, "first_training"

    last_dt = datetime.fromisoformat(last_trained)
    hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
    new_samples = current_samples - last_samples

    # Build model_version for decay lookup (same logic as confidence_decay_task)
    model_version = meta.get("model_version")
    if not model_version and last_trained:
        model_version = f"v{last_dt.strftime('%Y%m%d_%H%M%S')}"

    # B.2 Auto-retrain trigger by decay
    try:
        from app.services.database import SessionLocal
        from app.services.feature_importance_drift import get_latest_drift
        from app.services.confidence_decay_tracker import get_latest_decay
        from app.services.drift_detector import get_drift_status_for_signal

        with SessionLocal() as db:
            decay = get_latest_decay(db, model_version) if model_version else None
            fi_drift = get_latest_drift(db)

        decay_alert = decay and decay.get("is_alert") and (decay.get("divergence_pct") or 0) > 15
        fi_alert = fi_drift and fi_drift.get("is_alert")

        if decay_alert and fi_alert:
            return True, "critical_decay_confidence+features"
        if decay_alert:
            return True, "critical_decay_confidence"
        if fi_alert:
            return True, "critical_decay_features"
    except Exception as exc:
        logger.warning(f"[RETRAIN] Decay/drift check failed: {exc}")

    if hours_since >= MIN_HOURS:
        return True, f"{hours_since:.0f}h_since_last"
    if new_samples >= MIN_NEW_SAMPLES:
        return True, f"{new_samples}_new_signals"
    return False, f"{hours_since:.0f}h_{new_samples}_new"


def _get_bot_last_trained(bot_id: str) -> datetime | None:
    """Return the last training datetime for a bot, or None if never trained."""
    from ai import bot_registry
    meta = bot_registry.get_bot_model_meta(bot_id, "anti_fake")
    if meta and "trained_on" in meta:
        try:
            return datetime.fromisoformat(meta["trained_on"])
        except Exception:
            pass
    return None


def _count_bot_samples(bot_id: str, db, since_dt: datetime | None = None) -> tuple[int, int]:
    """Count total and new resolved samples for a bot.

    Returns (total_samples, new_samples_since_dt).
    If since_dt is None, new_samples == total_samples.
    """
    from sqlalchemy import func
    from app.models.ai_signal import AISignal
    from app.models.position import Position

    subq = (
        db.query(Position.extra_config["ai_signal_id"].astext.label("signal_id"))
        .filter(Position.bot_id == bot_id)
        .filter(Position.extra_config["ai_signal_id"].isnot(None))
        .subquery()
    )

    base_q = (
        db.query(AISignal)
        .filter(AISignal.id == func.cast(subq.c.signal_id, AISignal.id.type))
        .filter(AISignal.outcome.in_(["SUCCESS", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL", "CENSORED"]))
    )

    total = base_q.count()

    if since_dt:
        new = base_q.filter(AISignal.resolved_at > since_dt).count()
    else:
        new = total

    return total, new


def _train_single_bot(
    bot_id: str,
    bot_name: str,
    X_bot,
    y_bot,
    g_bot,
    sw_bot,
    sid_bot,
    db,
) -> bool:
    """Train anti-fake + ensemble + adaptive weights for a single bot.
    Returns True if anti-fake training succeeded.
    """
    import pandas as pd
    from ai.trainers.anti_fake_trainer import train_model
    from ai.trainers import ensemble_trainer
    from ai import bot_registry
    from app.models.llm_signal_diagnosis import LLMSignalDiagnosis
    from sqlalchemy import select, func, and_

    bot_af_artifact = None
    bot_af_metrics = None
    try:
        bot_af_artifact, bot_af_metrics = train_model(
            X_bot, y_bot, groups=g_bot, sample_weights=sw_bot
        )
        bot_registry.save_bot_model(bot_id, "anti_fake", {
            "model": bot_af_artifact["model"],
            "feature_names": bot_af_artifact["feature_names"],
            "metrics": bot_af_metrics,
            "trained_on": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            f"[RETRAIN-BOT] {bot_name}: anti-fake AUC={bot_af_metrics['auc']:.3f} "
            f"ACC={bot_af_metrics['accuracy']:.3f}"
        )
    except Exception as bot_af_exc:
        logger.warning(f"[RETRAIN-BOT] {bot_name}: anti-fake training failed: {bot_af_exc}")
        return False

    # Train ensemble
    try:
        bot_llm_scores = pd.Series([0.5] * len(X_bot), index=X_bot.index)
        try:
            subq = (
                select(
                    LLMSignalDiagnosis.ai_signal_id,
                    func.max(LLMSignalDiagnosis.created_at).label("max_created")
                )
                .where(LLMSignalDiagnosis.ai_signal_id.in_(sid_bot.tolist()))
                .group_by(LLMSignalDiagnosis.ai_signal_id)
                .subquery()
            )
            diags = (
                db.query(LLMSignalDiagnosis)
                .join(subq, and_(
                    LLMSignalDiagnosis.ai_signal_id == subq.c.ai_signal_id,
                    LLMSignalDiagnosis.created_at == subq.c.max_created
                ))
                .all()
            )
            diag_map = {str(d.ai_signal_id): d.diagnosis_json for d in diags}
            for idx, sid in sid_bot.items():
                diag = diag_map.get(sid, {})
                verdict = diag.get("verdict", "CLEAR")
                conf = diag.get("confidence", 50)
                base = 1.0 if verdict == "BLOCK" else 0.5 if verdict == "CAUTION" else 0.0
                bot_llm_scores.at[idx] = base * (conf / 100.0)
        except Exception:
            pass

        bot_ens_artifact, bot_ens_metrics = ensemble_trainer.train_ensemble(
            X_bot, y_bot, groups=g_bot, sample_weights=sw_bot, llm_scores=bot_llm_scores
        )
        bot_registry.save_bot_model(bot_id, "ensemble", {
            "meta_learner": bot_ens_artifact["meta_learner"],
            "meta_scaler": bot_ens_artifact["meta_scaler"],
            "base_models": bot_ens_artifact["base_models"],
            "base_calibrators": bot_ens_artifact.get("base_calibrators", {}),
            "feature_names": bot_ens_artifact["feature_names"],
            "meta_feature_names": bot_ens_artifact.get("meta_feature_names", ["xgb", "rf", "ridge"]),
            "use_llm": bot_ens_artifact.get("use_llm", False),
            "metrics": bot_ens_metrics,
            "trained_on": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            f"[RETRAIN-BOT] {bot_name}: ensemble AUC={bot_ens_metrics['ensemble_auc']:.3f} "
            f"weights={bot_ens_metrics['meta_weights']}"
        )
    except Exception as bot_ens_exc:
        logger.warning(f"[RETRAIN-BOT] {bot_name}: ensemble training failed: {bot_ens_exc}")

    # Build per-bot adaptive weights
    try:
        _build_and_save_adaptive_weights(
            bot_af_metrics.get("feature_importance", {}), db, bot_id=bot_id
        )
    except Exception as w_exc:
        logger.warning(f"[RETRAIN-BOT] {bot_name}: adaptive weights failed: {w_exc}")

    return True


def _bootstrap_bots() -> None:
    """Clone peer or global models for bots that don't have their own model."""
    from ai import bot_registry
    from app.models.bot_config import BotConfig
    from app.services.database import SessionLocal
    from ai import registry as anti_fake_registry
    from ai import ensemble_registry
    import pickle

    try:
        with SessionLocal() as db:
            active_bots = db.query(BotConfig).filter(
                BotConfig.ai_signal_mode == True,
                BotConfig.status == "active",
            ).all()

            bots_needing_bootstrap = [
                b for b in active_bots
                if not bot_registry.model_ready_for_bot(str(b.id))
            ]
            if bots_needing_bootstrap:
                logger.info(
                    f"[RETRAIN-BOOTSTRAP] {len(bots_needing_bootstrap)} bots need model bootstrap"
                )

            for bot in bots_needing_bootstrap:
                bot_id_str = str(bot.id)
                bot_symbol = bot.symbol.replace("/", "").replace(":", "") if bot.symbol else ""

                # 1. Try same-ticker bot with best per-bot AUC
                best_peer = None
                best_auc = 0.0
                for peer in active_bots:
                    if peer.id == bot.id:
                        continue
                    peer_symbol = peer.symbol.replace("/", "").replace(":", "") if peer.symbol else ""
                    if peer_symbol != bot_symbol:
                        continue
                    if not bot_registry.model_ready_for_bot(str(peer.id)):
                        continue
                    peer_data = bot_registry.get_bot_model_meta(str(peer.id), "anti_fake")
                    peer_auc = peer_data.get("metrics", {}).get("auc", 0.0) if peer_data else 0.0
                    if peer_auc > best_auc:
                        best_auc = peer_auc
                        best_peer = peer

                source_type = None
                if best_peer and best_auc >= 0.55:
                    for mtype in ["anti_fake", "ensemble"]:
                        peer_data = bot_registry._load_bot_model(str(best_peer.id), mtype)
                        if peer_data:
                            bot_registry.save_bot_model(bot_id_str, mtype, peer_data)
                    source_type = f"peer:{best_peer.bot_name}(AUC={best_auc:.3f})"
                else:
                    # 2. Fallback: clone global models
                    global_af = anti_fake_registry.model_info()
                    global_ens = ensemble_registry.model_info()
                    if global_af.get("ready") and global_ens.get("ready"):
                        global_af_path = Path(__file__).parent.parent.parent / "ai" / "models" / "anti_fake_v1.pkl"
                        global_ens_path = Path(__file__).parent.parent.parent / "ai" / "models" / "ensemble_v1.pkl"
                        if global_af_path.exists():
                            with open(global_af_path, "rb") as f:
                                bot_registry.save_bot_model(bot_id_str, "anti_fake", pickle.load(f))
                        if global_ens_path.exists():
                            with open(global_ens_path, "rb") as f:
                                bot_registry.save_bot_model(bot_id_str, "ensemble", pickle.load(f))
                        source_type = "global"

                if source_type:
                    logger.info(
                        f"[RETRAIN-BOOTSTRAP] {bot.bot_name}: bootstrapped from {source_type}"
                    )
                else:
                    logger.warning(
                        f"[RETRAIN-BOOTSTRAP] {bot.bot_name}: no source available for bootstrap"
                    )
    except Exception as boot_exc:
        logger.warning(f"[RETRAIN] Bootstrap phase failed: {boot_exc}")


@shared_task(
    name="app.tasks.ai_retrain_task.retrain_anti_fake",
    queue="default",
)
def retrain_anti_fake() -> dict:
    import pandas as pd
    from ai.dataset_builder import build_dataset_with_metadata_sync
    from ai.trainers.anti_fake_trainer import (
        train_model, save_artifact, MIN_SAMPLES as TRAINER_MIN,
    )
    from ai.trainers import ensemble_trainer
    from ai.validation.walk_forward import (
        walk_forward_validate, should_accept_new_model,
    )
    from ai import registry
    from ai import ensemble_registry
    from xgboost import XGBClassifier

    # ── Model age monitoring ─────────────────────────────────────────
    meta = _load_meta()
    last_trained = meta.get("last_trained_at")
    if last_trained:
        hours_since = (datetime.now(timezone.utc) - datetime.fromisoformat(last_trained)).total_seconds() / 3600
        if hours_since > 48:
            logger.warning(
                f"[RETRAIN] MODEL STALE: {hours_since:.1f}h since last training. "
                f"Expected every 6-24h. Check Celery beat/worker health."
            )

    X, y_binary, y_returns, groups, sample_weights, signal_ids = build_dataset_with_metadata_sync(max_samples=5000)

    if len(X) < TRAINER_MIN:
        logger.info(
            f"[RETRAIN] Skipping — only {len(X)}/{TRAINER_MIN} resolved signals"
        )
        return {"status": "insufficient_data", "samples": len(X), "required": TRAINER_MIN}

    should, reason = _should_retrain(len(X))
    if not should:
        logger.info(f"[RETRAIN] Skipping — {reason}")
        return {"status": "skipped", "reason": reason, "samples": len(X)}

    # Fase 2: dataset builder now requires realistic labels, so all labels are realistic.
    real_trade_count = int((sample_weights > 1.5).sum()) if sample_weights is not None else 0
    logger.info(
        f"[RETRAIN] Training on {len(X)} samples… (reason: {reason}). "
        f"Labels: realistic={len(X)} (100%). "
        f"Real trades (weighted): {real_trade_count}"
    )

    # ── Train model (not saved yet) ──────────────────────────────────────────
    artifact, metrics = train_model(X, y_binary, groups=groups, sample_weights=sample_weights)

    # ── Walk-Forward Validation Gate ─────────────────────────────────────────
    logger.info("[RETRAIN] Running walk-forward validation gate…")
    try:
        # v3: WFV proxy now validates the ACTUAL anti-fake target (FAILURE=1).
        # scale_pos_weight up-weights the minority class (FAILURE).
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

        # Load old metrics for comparison (supports legacy keys for backward compat)
        old_meta = _load_meta()
        # v3: classification-focused metrics.  Legacy fallbacks are ONLY used for
        # the same *type* of metric (auc≈sharpe both measure discriminative power).
        # Profit factor / win rate are NOT valid fallbacks for precision/recall.
        old_metrics = {
            # Classification metrics only. Trading metrics (sharpe, pf, etc.) are
            # advisory and must NOT be used to accept/reject the model.
            "auc": old_meta.get("wf_auc", old_meta.get("auc", old_meta.get("oof_auc", 0.55))),
            "precision": old_meta.get("wf_precision", 0.30),
            "recall": old_meta.get("wf_recall", 0.30),
            "f1": old_meta.get("wf_f1", 0.25),
        }

        if "error" in wf_result:
            logger.warning(f"[RETRAIN] Walk-forward failed: {wf_result['error']}")
            wf_passed = False  # Do not accept a model we could not validate
            wf_reason = f"wf_error:{wf_result['error']}"
        else:
            wf_metrics = wf_result["aggregated"]
            wf_stability = wf_result.get("stability")

            # The WF proxy trains a fresh XGBoost on small sliding windows; its fold
            # AUC is noisy and can collapse in regime-change periods. Use the trained
            # anti_fake model's own GroupKFold fold AUCs for the temporal stability gate
            # — they represent the ACTUAL model's cross-sectional stability.
            from ai.validation.walk_forward import _check_temporal_stability
            model_fold_aucs = metrics.get("fold_aucs") or []
            model_stability = (
                _check_temporal_stability(model_fold_aucs, [])
                if len(model_fold_aucs) >= 2 else None
            )

            wf_passed, wf_reason = should_accept_new_model(old_metrics, wf_metrics, model_stability)
            logger.info(
                f"[RETRAIN] WF gate: passed={wf_passed} reason={wf_reason} "
                f"auc={wf_metrics.get('auc', 0):.3f} pr={wf_metrics.get('precision', 0):.3f} "
                f"rc={wf_metrics.get('recall', 0):.3f} f1={wf_metrics.get('f1', 0):.3f} "
                f"lift={wf_metrics.get('auc_lift', 0):.3f} | "
                f"model_stability={model_stability.get('min_auc', 0):.3f}"
                f"±{model_stability.get('auc_std', 0):.3f} passes={model_stability.get('passes')} | "
                f"wf_proxy_stability={wf_stability.get('min_auc', 0):.3f}"
                f"±{wf_stability.get('auc_std', 0):.3f} (advisory)"
                if model_stability and wf_stability else ""
            )

    except Exception as wf_exc:
        logger.warning(f"[RETRAIN] Walk-forward exception: {wf_exc}")
        wf_passed = False  # Do not accept a model we could not validate
        wf_reason = f"exception:{wf_exc}"
        wf_result = {"error": str(wf_exc)}
        wf_metrics = None
        old_metrics = {
            "auc": old_meta.get("wf_auc", old_meta.get("auc", old_meta.get("oof_auc", 0.5))) if 'old_meta' in locals() else 0.5,
            "precision": old_meta.get("wf_precision", 0.0) if 'old_meta' in locals() else 0.0,
        }

    if not wf_passed:
        logger.warning(f"[RETRAIN] MODEL REJECTED by walk-forward gate: {wf_reason}")
        del artifact, X, y_binary, y_returns
        gc.collect()
        return {
            "status": "rejected",
            "reason": wf_reason,
            "wf_result": wf_result.get("aggregated") if isinstance(wf_result, dict) else None,
            **metrics,
        }

    # ── Persist Walk-Forward Validation log to DB ────────────────────────────
    model_version = f"v{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    try:
        from app.models.model_validation_log import ModelValidationLog
        from app.services.database import SessionLocal

        top_feats = metrics.get("feature_importance", {})
        top_features_list = [
            {"feature": k, "importance": float(v)}
            for k, v in sorted(top_feats.items(), key=lambda x: -x[1])[:20]
        ] if top_feats else []

        def _safe_float(v):
            if v is None:
                return None
            return float(v)

        mvl = ModelValidationLog(
            model_version=model_version,
            model_type="anti_fake_xgb",
            trained_at=datetime.now(timezone.utc),
            samples_used=len(X),
            features_used=len(X.columns),
            feature_names=list(X.columns),
            wf_passed=wf_passed,
            wf_reason=wf_reason,
            wf_folds=wf_result.get("folds", 0) if isinstance(wf_result, dict) else 0,
            wf_sharpe=_safe_float(wf_metrics.get("sharpe")) if wf_metrics else None,
            wf_profit_factor=_safe_float(wf_metrics.get("profit_factor")) if wf_metrics else None,
            wf_expectancy=_safe_float(wf_metrics.get("expectancy")) if wf_metrics else None,
            wf_win_rate=_safe_float(wf_metrics.get("win_rate")) if wf_metrics else None,
            wf_max_drawdown=_safe_float(wf_metrics.get("max_drawdown")) if wf_metrics else None,
            wf_total_return=_safe_float(wf_metrics.get("total_return")) if wf_metrics else None,
            wf_fold_results=_to_json_safe(wf_result.get("fold_results")) if isinstance(wf_result, dict) else None,
            old_sharpe=_safe_float(old_metrics.get("sharpe")) if wf_metrics else None,
            old_profit_factor=_safe_float(old_metrics.get("profit_factor")) if wf_metrics else None,
            old_expectancy=_safe_float(old_metrics.get("expectancy")) if wf_metrics else None,
            test_auc=_safe_float(metrics.get("auc")),
            test_accuracy=_safe_float(metrics.get("accuracy")),
            test_precision=_safe_float(metrics.get("precision")),
            test_recall=_safe_float(metrics.get("recall")),
            top_features=_to_json_safe(top_features_list),
        )
        with SessionLocal() as db:
            db.add(mvl)
            db.commit()
            logger.info(f"[RETRAIN] ModelValidationLog persisted — id={mvl.id} version={model_version}")
    except Exception as log_exc:
        logger.warning(f"[RETRAIN] Failed to persist ModelValidationLog: {log_exc}")

    # ── Accept model: save artifact + build weights ──────────────────────────
    save_artifact(artifact)

    # ── Train Hybrid Ensemble ────────────────────────────────────────────────
    logger.info("[RETRAIN] Training hybrid ensemble (XGB+RF+LR + meta-learner)…")
    try:
        # Build LLM scores vector aligned with X rows for meta-learner
        llm_scores = pd.Series([0.5] * len(X), index=X.index)
        try:
            from app.models.llm_signal_diagnosis import LLMSignalDiagnosis
            from sqlalchemy import select, func, and_
            with SessionLocal() as db:
                subq = (
                    select(
                        LLMSignalDiagnosis.ai_signal_id,
                        func.max(LLMSignalDiagnosis.created_at).label("max_created")
                    )
                    .where(LLMSignalDiagnosis.ai_signal_id.in_(signal_ids.tolist()))
                    .group_by(LLMSignalDiagnosis.ai_signal_id)
                    .subquery()
                )
                diags = (
                    db.query(LLMSignalDiagnosis)
                    .join(subq, and_(
                        LLMSignalDiagnosis.ai_signal_id == subq.c.ai_signal_id,
                        LLMSignalDiagnosis.created_at == subq.c.max_created
                    ))
                    .all()
                )
                diag_map = {str(d.ai_signal_id): d.diagnosis_json for d in diags}
                for idx, sid in signal_ids.items():
                    diag = diag_map.get(sid, {})
                    verdict = diag.get("verdict", "CLEAR")
                    conf = diag.get("confidence", 50)
                    # Scale: BLOCK=1.0, CAUTION=0.5, CLEAR=0.0; shift by confidence
                    base = 1.0 if verdict == "BLOCK" else 0.5 if verdict == "CAUTION" else 0.0
                    llm_scores.at[idx] = base * (conf / 100.0)
        except Exception as llm_exc:
            logger.warning(f"[RETRAIN] Failed to build llm_scores: {llm_exc}")

        ens_artifact, ens_metrics = ensemble_trainer.train_ensemble(
            X, y_binary, groups=groups, sample_weights=sample_weights, llm_scores=llm_scores
        )
        ensemble_trainer.save_artifact(ens_artifact)
        ensemble_registry.invalidate()
        logger.info(
            f"[RETRAIN] Ensemble trained — ensemble_auc={ens_metrics['ensemble_auc']} "
            f"xgb_auc={ens_metrics['xgb_oof_auc']} rf_auc={ens_metrics['rf_oof_auc']} "
            f"ridge_auc={ens_metrics['ridge_oof_auc']} weights={ens_metrics['meta_weights']}"
        )
    except Exception as ens_exc:
        logger.warning(f"[RETRAIN] Ensemble training failed: {ens_exc}")
        ens_metrics = None

    # NOTE: Per-bot training and bootstrap now handled by retrain_bot_models() task

    # Build adaptive confluence weights + feature importance drift (same session)
    with SessionLocal() as db:
        _build_and_save_adaptive_weights(metrics.get("feature_importance", {}), db)

        # ── Feature Importance Drift Tracking (B.1) ─────────────────────────
        try:
            from app.services.feature_importance_drift import compute_feature_importance_drift
            prev_meta = META_PATH
            prev_fi = {}
            prev_version = None
            if prev_meta.exists():
                import json
                with open(prev_meta) as f:
                    prev_data = json.load(f)
                prev_fi = prev_data.get("feature_importance", {})
                prev_version = prev_data.get("model_version")
            compute_feature_importance_drift(
                db=db,
                current_importance=metrics.get("feature_importance", {}),
                model_version=model_version,
                previous_model_version=prev_version,
                previous_importance=prev_fi if prev_fi else None,
            )
            logger.info(f"[RETRAIN] Feature importance drift tracked for {model_version}")
        except Exception as fi_exc:
            logger.warning(f"[RETRAIN] Feature importance drift tracking failed: {fi_exc}")

    # Persist metadata base (needed before threshold optimization)
    meta_payload = _to_json_safe({
        "last_trained_at": datetime.now(timezone.utc).isoformat(),
        "samples_at_training": len(X),
        "reason": reason,
        "realistic_labels": realistic_count,
        "ideal_labels": len(X) - realistic_count,
        **metrics,
    })

    # Evaluación 1: Threshold optimization — only during retrain
    try:
        from app.services.threshold_optimizer import optimize_model_thresholds
        from app.services.database import SessionLocal
        from app.models.ai_signal import AISignal
        from sqlalchemy import select, and_

        with SessionLocal() as db:
            # Use resolved signals with success_probability as validation data
            # (proxy for walk-forward test set — signals scored by previous model)
            stmt = (
                select(AISignal)
                .where(
                    and_(
                        AISignal.realistic_outcome.in_(["SUCCESS", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL", "CENSORED"]),
                        AISignal.success_probability.isnot(None),
                        AISignal.score.isnot(None),
                        AISignal.resolved_at.isnot(None),
                        AISignal.realistic_pnl_pct.isnot(None),
                    )
                )
                .order_by(AISignal.resolved_at.desc())
                .limit(2000)
            )
            val_signals = db.execute(stmt).scalars().all()
            val_data = [
                {
                    "score": s.score,
                    "success_probability": s.success_probability,
                    "outcome": s.realistic_outcome,
                    "pnl_pct": s.realistic_pnl_pct,
                }
                for s in val_signals
            ]

        threshold_result = optimize_model_thresholds(val_data)
        if threshold_result and threshold_result.get("status") == "ok":
            meta_payload["optimized_thresholds"] = threshold_result
            logger.info(
                f"[RETRAIN] Thresholds optimized — score≥{threshold_result['score_threshold']} "
                f"prob≤{threshold_result['prob_threshold']} "
                f"sharpe={threshold_result['expected_sharpe']} "
                f"n={threshold_result['n_trades']}"
            )
        else:
            logger.info(f"[RETRAIN] Threshold optimization skipped: {threshold_result}")
    except Exception as to_exc:
        logger.warning(f"[RETRAIN] Threshold optimization failed: {to_exc}")

    # Persist metadata with WF metrics (classification-focused + legacy)
    if wf_metrics:
        meta_payload.update({
            "wf_auc": wf_metrics.get("auc"),
            "wf_precision": wf_metrics.get("precision"),
            "wf_recall": wf_metrics.get("recall"),
            "wf_f1": wf_metrics.get("f1"),
            "wf_logloss": wf_metrics.get("logloss"),
            "wf_auc_lift": wf_metrics.get("auc_lift"),
            # Legacy advisory trading metrics
            "wf_sharpe": wf_metrics.get("sharpe"),
            "wf_profit_factor": wf_metrics.get("profit_factor"),
            "wf_expectancy": wf_metrics.get("expectancy"),
            "wf_win_rate": wf_metrics.get("win_rate"),
            "wf_max_drawdown": wf_metrics.get("max_drawdown"),
            "wf_trades": wf_metrics.get("trades"),
        })
    # Store model_version so decay tracker can reference it
    meta_payload["model_version"] = model_version
    _save_meta(meta_payload)

    # Liberar memoria pesada explícitamente
    del artifact, X, y_binary, y_returns
    gc.collect()

    registry.invalidate()  # flush in-memory cache

    log_msg = f"[RETRAIN] Done — XGB AUC={metrics['auc']} ACC={metrics['accuracy']} WF={wf_reason}"
    if ens_metrics:
        log_msg += f" | Ensemble AUC={ens_metrics['ensemble_auc']}"
    logger.info(log_msg)
    result = {"status": "trained", "reason": reason, **metrics}
    if ens_metrics:
        result["ensemble_metrics"] = ens_metrics
    return result


_RETRAIN_SCHEDULE_HOURS = {
    "15m": 1, "30m": 1,
    "1h": 2, "2h": 2,
    "4h": 4,
    "1d": 6, "1w": 6,
}
_MIN_BOT_SAMPLES_FIRST = 50
_MIN_BOT_SAMPLES_RETRAIN = 100
_MIN_BOT_NEW_SAMPLES = 15


@shared_task(
    name="app.tasks.ai_retrain_task.retrain_bot_models",
    queue="default",
)
def retrain_bot_models() -> dict:
    """Train per-bot models with timeframe-aware frequency.

    Runs every hour via Celery Beat. For each active AI bot:
      - Checks hours since last training against its timeframe schedule
      - Applies hybrid sample threshold (first train: ≥50, retrain: ≥100 total OR ≥15 new)
      - Loads dataset once, trains only eligible bots
      - Bootstraps bots without models at the end
    """
    import pandas as pd
    from ai.dataset_builder import build_dataset_with_metadata_sync
    from app.models.bot_config import BotConfig
    from app.models.position import Position
    from app.services.database import SessionLocal

    # ── Identify eligible bots ───────────────────────────────────────────────
    bots_to_train: list[tuple] = []
    with SessionLocal() as db:
        active_bots = db.query(BotConfig).filter(
            BotConfig.ai_signal_mode == True,
            BotConfig.status == "active",
        ).all()

        for bot in active_bots:
            bot_id_str = str(bot.id)
            last_trained = _get_bot_last_trained(bot_id_str)
            min_hours = _RETRAIN_SCHEDULE_HOURS.get(bot.timeframe, 6)

            if last_trained is not None:
                hours_since = (datetime.now(timezone.utc) - last_trained).total_seconds() / 3600
                if hours_since < min_hours:
                    logger.debug(
                        f"[RETRAIN-BOT] {bot.bot_name}: skip ({hours_since:.1f}h < {min_hours}h)"
                    )
                    continue

            total, new = _count_bot_samples(bot_id_str, db, last_trained)

            is_first = last_trained is None
            if is_first:
                if total < _MIN_BOT_SAMPLES_FIRST:
                    logger.info(
                        f"[RETRAIN-BOT] {bot.bot_name}: {total} total samples < {_MIN_BOT_SAMPLES_FIRST}, skipping"
                    )
                    continue
            else:
                if total < _MIN_BOT_SAMPLES_RETRAIN and new < _MIN_BOT_NEW_SAMPLES:
                    logger.info(
                        f"[RETRAIN-BOT] {bot.bot_name}: {total} total / {new} new samples, skipping"
                    )
                    continue

            bots_to_train.append((bot, total, new, is_first))
            logger.info(
                f"[RETRAIN-BOT] {bot.bot_name}: eligible — total={total} new={new} first={is_first}"
            )

    results: list[dict] = []
    if bots_to_train:
        # ── Load symbol-specific datasets (primary) + global fallback ────────
        logger.info(f"[RETRAIN-BOT] Loading datasets for {len(bots_to_train)} bots…")

        # Cache: (symbol, timeframe) -> dataset  (avoid redundant loads)
        _sym_dataset_cache: dict[tuple, tuple] = {}

        # Global dataset as fallback for bots whose symbol lacks enough history
        logger.info("[RETRAIN-BOT] Loading global fallback dataset…")
        X_global, y_global, yret_global, g_global, sw_global, sid_global = (
            build_dataset_with_metadata_sync(max_samples=5000)
        )

        # Build signal_id → bot_id map (used for global fallback only)
        with SessionLocal() as db:
            positions = db.query(Position).filter(
                Position.source == "ai_bot",
                Position.extra_config.isnot(None),
            ).all()

            sig_to_bots: dict[str, list[str]] = {}
            for pos in positions:
                sid = (pos.extra_config or {}).get("ai_signal_id")
                if sid:
                    sig_to_bots.setdefault(str(sid), []).append(str(pos.bot_id))

        # ── Train each eligible bot ──────────────────────────────────────────
        for bot, total, new, is_first in bots_to_train:
            bot_id_str = str(bot.id)
            sym_key = (bot.symbol, bot.timeframe)

            # ---- 1. Try symbol-specific dataset (independent world per symbol) ----
            if sym_key not in _sym_dataset_cache:
                try:
                    X_sym, y_sym, yret_sym, g_sym, sw_sym, sid_sym = (
                        build_dataset_with_metadata_sync(
                            max_samples=5000,
                            bot_ticker=bot.symbol,
                            bot_timeframe=bot.timeframe,
                        )
                    )
                    _sym_dataset_cache[sym_key] = (
                        X_sym, y_sym, yret_sym, g_sym, sw_sym, sid_sym
                    )
                    logger.info(
                        f"[RETRAIN-BOT] Symbol dataset loaded: {bot.symbol}/{bot.timeframe} "
                        f"({len(X_sym)} samples)"
                    )
                except Exception as exc:
                    logger.warning(
                        f"[RETRAIN-BOT] Failed to load symbol dataset for {bot.symbol}: {exc}"
                    )
                    _sym_dataset_cache[sym_key] = None

            sym_data = _sym_dataset_cache.get(sym_key)
            use_symbol = False
            X_bot = y_bot = g_bot = sw_bot = sid_bot = None
            bot_n = 0

            if sym_data is not None:
                X_sym, y_sym, _, g_sym, sw_sym, sid_sym = sym_data
                if len(X_sym) >= _MIN_BOT_SAMPLES_FIRST:
                    use_symbol = True
                    X_bot = X_sym.copy()
                    y_bot = y_sym.copy()
                    g_bot = g_sym.copy()
                    sw_bot = sw_sym.copy()
                    sid_bot = sid_sym.copy()
                    bot_n = len(X_bot)
                    logger.info(
                        f"[RETRAIN-BOT] {bot.bot_name}: using SYMBOL dataset "
                        f"({bot_n} samples for {bot.symbol}/{bot.timeframe})"
                    )

            # ---- 2. Fallback: global dataset filtered by bot's own signals ----
            if not use_symbol:
                bot_signal_ids = [
                    sid for sid, bids in sig_to_bots.items()
                    if bot_id_str in bids
                ]
                if not bot_signal_ids:
                    logger.info(
                        f"[RETRAIN-BOT] {bot.bot_name}: no symbol data and no executed "
                        f"signals in global dataset, skipping"
                    )
                    continue

                mask = sid_global.isin(bot_signal_ids)
                bot_n = int(mask.sum())
                if bot_n < _MIN_BOT_SAMPLES_FIRST:
                    logger.info(
                        f"[RETRAIN-BOT] {bot.bot_name}: {bot_n} samples in global dataset "
                        f"< {_MIN_BOT_SAMPLES_FIRST}, skipping"
                    )
                    continue

                X_bot = X_global.loc[mask].copy()
                y_bot = y_global.loc[mask].copy()
                g_bot = g_global.loc[mask].copy()
                sw_bot = sw_global.loc[mask].copy()
                sid_bot = sid_global.loc[mask].copy()
                logger.info(
                    f"[RETRAIN-BOT] {bot.bot_name}: using GLOBAL fallback dataset "
                    f"({bot_n} samples)"
                )

            # ---- 3. Train ----
            with SessionLocal() as db:
                success = _train_single_bot(
                    bot_id=bot_id_str,
                    bot_name=bot.bot_name,
                    X_bot=X_bot,
                    y_bot=y_bot,
                    g_bot=g_bot,
                    sw_bot=sw_bot,
                    sid_bot=sid_bot,
                    db=db,
                )

            results.append({
                "bot_id": bot_id_str,
                "bot_name": bot.bot_name,
                "trained": success,
                "samples": bot_n,
                "dataset": "symbol" if use_symbol else "global",
            })

            del X_bot, y_bot, g_bot, sw_bot, sid_bot
            gc.collect()

    # ── Bootstrap bots without models ────────────────────────────────────────
    _bootstrap_bots()

    return {
        "status": "trained" if results else "skipped",
        "bots": len(results),
        "results": results,
    }
