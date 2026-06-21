"""Build training dataset from resolved AISignal records.

X = 15 market-structure features + execution-quality features.
y = 1 if FAILURE (any type), 0 if SUCCESS.

Uses realistic_outcome when available, falling back to ideal outcome.
Excludes INCONCLUSIVE/EXPIRED and CENSORED signals from training.
CENSORED signals are counted for the ratio check (>30% rejects training)
but never fed to the binary classifier since their true outcome is unknown.
Includes execution analytics (slippage, gap frequency, fees) as features
to help the model learn the real-world cost of trading.

v2 — Added real-trade weighting:
  Signals linked to a real executed position get higher sample_weight
  so the model learns more from actual exchange outcomes than synthetic backtest.
"""
from __future__ import annotations

import pandas as pd
from datetime import datetime, timezone
from loguru import logger

from app.services.execution_analytics import get_profile_for_signal
from ai.services.causal_feature_builder import CausalFeatureBuilder

# Fecha de corte: solo usamos señales resueltas con el motor realista posterior a esta fecha.
# Esto rompe la contaminación de métricas/trades del motor antiguo.
CLEAN_CUTOFF = datetime(2026, 6, 10, tzinfo=timezone.utc)


FEATURE_COLS = [
    "fvg_aligned_count",
    "ob_distance_atr",
    "pd_position",
    "hour_utc",
    "day_of_week",
    "eq_highs_count",
    "eq_lows_count",
    "volume_ratio",
    "spread_atr",
    "score",
    # Timeframe as a confluence feature — the model learns that
    # an FVG in 15m is NOT the same as an FVG in 1d
    "timeframe_encoded",
    # Real vs paper as a feature — model learns quality differences
    "is_real_trade",
    # Execution-quality features
    "avg_entry_slippage",
    "gap_frequency",
    "fee_rate",
    "tp_fill_rate",
    # Encoded categoricals
    "trigger_ob",
    "trigger_fvg",
    "bias_bull",
    "sweep_bool",
    "break_choch",
    # HTF confluence — model learns that alignment with higher-timeframe
    # structural bias significantly improves edge (separate from scanner hard-gate)
    "htf_bias_bull",
    "htf_aligned",
    # Backtest engine connection — rolling historical metrics per ticker/tf
    # let the model learn when a symbol's recent simulated performance is strong
    "backtest_wr_30d",
    "backtest_pf_30d",
    "backtest_n_30d",
    # Forward structural levels — the model learns that a signal with TP1 at 3R
    # has lower success probability than one with TP1 at 0.8R, even if both score 75
    "tp1_distance_r",
    "tp1_strength",
    "forward_density",
    # Hybrid soft features: model learns risk curves instead of hard gates
    "pd_score",
    "killzone_score",
    "entry_type_re",
    "ltf_cdc_confirmed",
    # NOTE: LLM-derived features moved to llm_signal_diagnosis only —
    # they do NOT train the ML model to prevent circular dependency & leakage.
]

# Ordinal encoding for timeframe — higher = longer holding period
# This lets XGBoost learn that market-structure components behave
# differently across temporalities.
TF_ORDINAL = {
    "1m": 1, "3m": 2, "5m": 3, "15m": 4, "30m": 5,
    "1h": 6, "2h": 7, "4h": 8, "6h": 9, "8h": 10,
    "12h": 11, "1d": 12, "3d": 13, "1w": 14,
}

# Quality weights for signals based on (real vs paper) AND (same vs different timeframe)
# The model should learn from:
#   - Real trades (ground truth, highest weight)
#   - Paper trades SAME timeframe (simulation, medium weight)
#   - Real trades DIFFERENT timeframe (real but different dynamics, low weight)
#   - Paper trades DIFFERENT timeframe (unreliable, zero weight)
_QUALITY_WEIGHTS = {
    ("real", "same_tf"): 2.0,
    ("paper", "same_tf"): 1.0,
    ("real", "diff_tf"): 0.3,
    ("paper", "diff_tf"): 0.0,
}


def _get_signal_quality_map(db, target_timeframe: str | None = None) -> dict[str, float]:
    """Return {signal_id: quality_weight} where weight depends on:
    - real vs paper execution
    - same vs different timeframe relative to target_timeframe

    If target_timeframe is None, all real trades get 2.0 and all paper gets 0.5
    (used for global model training where timeframe is a feature, not a filter).
    """
    try:
        from app.models.position import Position
        from app.models.bot_config import BotConfig
        from app.models.ai_signal import AISignal
        from sqlalchemy import func

        # Join Position → BotConfig → AISignal to get both real/paper status AND timeframe
        # Filtramos por fecha de corte para no mezclar posiciones antiguas del motor viejo.
        rows = (
            db.query(
                Position.extra_config["ai_signal_id"].astext.label("signal_id"),
                BotConfig.paper_balance_id.is_(None).label("is_real"),
                AISignal.timeframe.label("signal_timeframe"),
            )
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .join(AISignal, AISignal.id == func.cast(Position.extra_config["ai_signal_id"].astext, AISignal.id.type))
            .filter(Position.extra_config["ai_signal_id"].isnot(None))
            .filter(AISignal.created_at >= CLEAN_CUTOFF)
            .all()
        )

        result = {}
        for r in rows:
            sid = r.signal_id
            if not sid:
                continue
            is_real = r.is_real
            sig_tf = r.signal_timeframe or "1h"

            if target_timeframe is None:
                # Global training: timeframe is a feature, not a filter.
                # Real trades get full weight, paper gets reduced weight.
                result[sid] = 2.0 if is_real else 0.5
            else:
                same_tf = (sig_tf == target_timeframe)
                key = ("real" if is_real else "paper", "same_tf" if same_tf else "diff_tf")
                result[sid] = _QUALITY_WEIGHTS[key]

        return result
    except Exception as exc:
        logger.warning(f"[DatasetBuilder] _get_signal_quality_map failed: {exc}")
        return {}


def _theoretical_pnl(sig) -> float:
    """Compute theoretical PnL from signal levels when realistic_pnl_pct is unavailable.

    Uses TP1 for SUCCESS and SL for FAILURE/BEHAVIORAL. Falls back to ±1.0 only
    when price levels are missing, preventing the inflated WF metrics caused by
    the previous hardcoded +1.5/-1.0 synthetic defaults.
    """
    try:
        entry = float(sig.entry_price) if sig.entry_price else 0.0
        if entry <= 0:
            return 1.0 if sig.outcome == "SUCCESS" else -1.0
        is_long = sig.direction == "long"
        if sig.outcome == "SUCCESS" and sig.take_profit_1:
            tp = float(sig.take_profit_1)
            ret = (tp - entry) / entry * 100 if is_long else (entry - tp) / entry * 100
            return round(ret, 3)
        if sig.outcome in ("FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL") and sig.stop_loss:
            sl = float(sig.stop_loss)
            ret = (sl - entry) / entry * 100 if is_long else (entry - sl) / entry * 100
            return round(ret, 3)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return 1.0 if sig.outcome == "SUCCESS" else -1.0


def build_dataset_with_metadata_sync(max_samples: int = 5000, target_timeframe: str | None = None, bot_ticker: str | None = None, bot_timeframe: str | None = None) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Build dataset including returns for walk-forward validation.

    Args:
        max_samples: maximum number of latest resolved signals to load.
        target_timeframe: if provided, paper trades from the SAME timeframe are included
                          with reduced weight. If None, all real trades get full weight
                          and all paper gets reduced weight (global training).
        bot_ticker: if provided, filter signals to this ticker only (bot-specific training).
        bot_timeframe: if provided, filter signals to this timeframe only.

    Returns:
        (X, y_binary, y_returns, groups, sample_weights, signal_ids) where:
        - X: feature matrix
        - y_binary: 0=success, 1=failure (for training)
        - y_returns: realistic_pnl_pct (for WF evaluation)
        - groups: ticker+timeframe for GroupKFold
        - sample_weights: weighted by data quality (real vs paper, same vs diff tf)
        - signal_ids: UUIDs aligned with X rows
    """
    from app.models.ai_signal import AISignal
    from app.services.database import SessionLocal

    with SessionLocal() as db:
        query = (
            db.query(AISignal)
            .filter(
                AISignal.outcome.in_(["SUCCESS", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL", "CENSORED"]),
                AISignal.realistic_outcome.isnot(None),
                AISignal.resolved_at >= CLEAN_CUTOFF,
            )
        )
        if bot_ticker:
            query = query.filter(AISignal.ticker == bot_ticker)
        if bot_timeframe:
            query = query.filter(AISignal.timeframe == bot_timeframe)

        rows = (
            query
            .order_by(AISignal.resolved_at.desc().nullslast())
            .limit(max_samples)
            .all()
        )
        quality_map = _get_signal_quality_map(db, target_timeframe)

    X, y_binary, groups, sample_weights, signal_ids = _build_from_rows(rows, quality_map)

    # Build a lookup of signal_id -> return
    id_to_return = {}
    for s in rows:
        if not s.features:
            continue
        ret = s.realistic_pnl_pct
        if ret is None:
            ret = _theoretical_pnl(s)
        id_to_return[str(s.id)] = ret

    returns = [id_to_return.get(sid, -1.0) for sid in signal_ids]
    y_returns = pd.Series(returns, index=X.index)
    return X, y_binary, y_returns, groups, sample_weights, signal_ids


def build_dataset_with_returns_sync(max_samples: int = 5000, target_timeframe: str | None = None) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Backward-compatible wrapper returning only X, y_binary, y_returns."""
    X, y_binary, y_returns, _, _, _ = build_dataset_with_metadata_sync(max_samples, target_timeframe)
    return X, y_binary, y_returns



def _build_from_rows(rows, signal_quality_map: dict[str, float] | None = None) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.Series]:
    records = []
    groups = []
    weights = []
    signal_ids = []
    quality_map = signal_quality_map or {}
    causal_builder = CausalFeatureBuilder()

    rejected_causal = 0
    censored_count = 0
    total_resolved = 0

    for s in rows:
        if not s.features:
            continue
        rec = dict(s.features)
        rec["score"] = s.score or 0
        # Timeframe as a learned confluence — the model discovers that
        # FVG/OB/CHoCH behave differently across temporalities
        rec["timeframe_encoded"] = TF_ORDINAL.get(s.timeframe, 6)

        effective_outcome = s.realistic_outcome or s.outcome

        # Data quality weight: real_same_tf > paper_same_tf > real_diff_tf > paper_diff_tf
        base_weight = quality_map.get(str(s.id), 0.3)
        is_real = base_weight >= 1.5  # real signals have weight >= 1.5

        # Evaluación 1+3: CENSORED handling — excluded from binary classifier training.
        # CENSORED signals are counted for the ratio check (>30% rejects training)
        # but never fed to the binary model since their true outcome is unknown.
        if effective_outcome == "CENSORED":
            censored_count += 1
            total_resolved += 1
            continue
        elif effective_outcome == "SUCCESS":
            rec["label"] = 0
            rec["failure_type"] = (s.features or {}).get("failure_type", "UNKNOWN")
            weight = base_weight
        elif effective_outcome in ("FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL"):
            rec["label"] = 1
            rec["failure_type"] = (s.features or {}).get("failure_type", "UNKNOWN")
            weight = base_weight
        else:
            continue  # PENDING or unknown — exclude from training

        total_resolved += 1

        # Causal feature builder — prefer causal, fallback to symbol profile
        # Historical signals may not have enough causal data; use symbol profile
        try:
            causal = causal_builder.build(s.ticker, s.signal_time)
            if causal.is_complete:
                rec["avg_entry_slippage"] = causal.avg_slippage_30d
                rec["gap_frequency"] = causal.gap_frequency_90d
                rec["fee_rate"] = causal.fee_rate
                rec["tp_fill_rate"] = causal.tp_fill_rate_30d
            else:
                # Fallback to symbol profile (not imputation — exchange-reported averages)
                profile = get_profile_for_signal(s.ticker, s.timeframe)
                rec["avg_entry_slippage"] = profile.avg_entry_slippage_pct
                rec["gap_frequency"] = profile.gap_frequency
                rec["fee_rate"] = profile.fee_rate
                rec["tp_fill_rate"] = profile.tp_wick_fill_rate
        except Exception:
            # Fallback to symbol profile on any error
            try:
                profile = get_profile_for_signal(s.ticker, s.timeframe)
                rec["avg_entry_slippage"] = profile.avg_entry_slippage_pct
                rec["gap_frequency"] = profile.gap_frequency
                rec["fee_rate"] = profile.fee_rate
                rec["tp_fill_rate"] = profile.tp_wick_fill_rate
            except Exception:
                rejected_causal += 1
                continue  # No profile available — reject

        # NOTE: LLM features intentionally excluded from ML training set.
        # They live in llm_signal_diagnosis table for human-readable
        # post-trade analysis only.
        rec["is_real_trade"] = int(is_real)

        records.append(rec)
        groups.append(f"{s.ticker}_{s.timeframe or 'unknown'}")
        weights.append(weight)
        signal_ids.append(str(s.id))

    # Evaluación 1+3: Reject training if >30% CENSORED
    if total_resolved > 0 and censored_count / total_resolved > 0.30:
        logger.warning(
            f"[DatasetBuilder] Rejecting training: {censored_count}/{total_resolved} "
            f"({censored_count/total_resolved:.1%}) CENSORED signals exceed 30% threshold"
        )
        empty = pd.DataFrame()
        empty_s = pd.Series(dtype=float)
        return empty, empty_s, empty_s, empty_s, empty_s

    if rejected_causal > 0:
        logger.info(
            f"[DatasetBuilder] Rejected {rejected_causal}/{len(rows)} signals due to "
            f"insufficient causal feature data (no imputation)"
        )

    if not records:
        empty = pd.DataFrame()
        empty_s = pd.Series(dtype=float)
        return empty, empty_s, empty_s, empty_s, empty_s

    df = pd.DataFrame(records)
    groups = pd.Series(groups, dtype="category")
    sample_weights = pd.Series(weights, index=df.index)
    signal_ids = pd.Series(signal_ids, index=df.index)

    # Inject micro-noise into execution-quality features if they have zero variance.
    # XGBoost ignores features with no variance; this ensures they remain learnable.
    _EXEC_FEATURES = ["avg_entry_slippage", "gap_frequency", "fee_rate", "tp_fill_rate"]
    import numpy as np
    for feat in _EXEC_FEATURES:
        if feat in df.columns and df[feat].nunique(dropna=False) <= 1:
            noise = np.random.normal(0, 0.001, size=len(df))
            df[feat] = df[feat].astype(float) + noise
            logger.info(
                f"[DatasetBuilder] Injected N(0,0.001) noise into {feat} "
                f"(zero variance detected)"
            )

    # Encode categoricals
    df["trigger_ob"]   = (df.get("trigger",    "") == "ob").astype(int)
    df["trigger_fvg"]  = (df.get("trigger",    "") == "fvg").astype(int)
    df["bias_bull"]    = (df.get("bias",        "") == "bull").astype(int)
    df["sweep_bool"]   = df.get("sweep_detected", False).fillna(False).astype(int)
    df["break_choch"]  = (df.get("break_type", "") == "CHoCH").astype(int)
    df["htf_bias_bull"] = (df.get("htf_bias", "") == "bull").astype(int)
    df["htf_aligned"]  = df.get("htf_aligned", False).fillna(False).astype(int)
    # Hybrid soft features
    df["entry_type_re"] = (df.get("entry_type", "") == "RE").astype(int)
    df["ltf_cdc_confirmed"] = df.get("ltf_cdc_confirmed", False).fillna(False).astype(int)

    available = [c for c in FEATURE_COLS if c in df.columns]
    X = df[available].fillna(0)
    y = df["label"]

    return X, y, groups, sample_weights, signal_ids
