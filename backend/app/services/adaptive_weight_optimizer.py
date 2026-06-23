"""
Adaptive Weight Optimizer — recalibrates confluence engine weights based on
historical signal outcomes (backtested SUCCESS vs FAILURE rates).

Run periodically (daily/weekly) to let the model learn which components
actually predict success in the current market regime.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.models.ai_signal import AISignal

# ── Constants ────────────────────────────────────────────────────────────────
_WEIGHT_PATH = Path("/app/ai/models/adaptive_weights.json")
_MIN_SAMPLES_PER_COMPONENT = 30  # minimum resolved signals to trust a delta
_BASELINE_WEIGHTS = {
    "structure_CHoCH": 20.0,
    "structure_BOS": 12.0,
    "trigger_OB": 15.0,
    "trigger_FVG": 10.0,
    "fvg_context": 4.0,  # per aligned FVG, capped at 12
    "sweep": 18.0,
    "pd_array": 10.0,
    "killzone": 10.0,
    "eq_obstacle": 8.0,
}
_MAX_CONFLUENCE_ABS = 85.0  # trending CHoCH + OB + 3FVG + sweep + P/D + killzone


@dataclass(frozen=True)
class ComponentStats:
    present_count: int
    present_wins: int
    absent_count: int
    absent_wins: int
    present_wr: float
    absent_wr: float
    delta_wr: float
    present_pnl: float
    absent_pnl: float
    delta_pnl: float
    suggested_weight: float


def _baseline_wr(rows: list) -> float:
    """Global win rate across all resolved rows."""
    resolved = [r for r in rows if r.outcome in ("SUCCESS", "FAILURE", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL")]
    if not resolved:
        return 0.0
    wins = sum(1 for r in resolved if r.outcome == "SUCCESS")
    return wins / len(resolved)


def _component_stats(
    rows: list,
    predicate,
    baseline_wr: float,
    base_weight: float,
) -> ComponentStats:
    """Compute PnL-realistic delta for a component predicate.

    Uses realistic PnL (not just win rate) to adjust weights, because a
    component can increase win rate while reducing average PnL due to
    worse risk/reward (e.g. sweep signals with wide stops).
    """
    present = [r for r in rows if predicate(r)]
    absent = [r for r in rows if not predicate(r)]

    present_wins = sum(1 for r in present if r.outcome == "SUCCESS")
    absent_wins = sum(1 for r in absent if r.outcome == "SUCCESS")

    present_wr = present_wins / len(present) if present else 0.0
    absent_wr = absent_wins / len(absent) if absent else 0.0
    delta_wr = present_wr - absent_wr

    # Realistic PnL delta (primary metric for weight adjustment)
    present_pnl = sum(
        (r.realistic_pnl_pct or r.pnl_pct or 0.0) * getattr(r, '_aw_weight', 1.0)
        for r in present if r.outcome in ("SUCCESS", "FAILURE", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL")
    ) / sum(getattr(r, '_aw_weight', 1.0) for r in present if r.outcome in ("SUCCESS", "FAILURE", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL")) if present else 0.0

    absent_pnl = sum(
        (r.realistic_pnl_pct or r.pnl_pct or 0.0) * getattr(r, '_aw_weight', 1.0)
        for r in absent if r.outcome in ("SUCCESS", "FAILURE", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL")
    ) / sum(getattr(r, '_aw_weight', 1.0) for r in absent if r.outcome in ("SUCCESS", "FAILURE", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL")) if absent else 0.0

    delta_pnl = present_pnl - absent_pnl

    # Adjust weight based on PnL delta, with WR as secondary confirmation.
    # Clamp delta influence to ±20% (reduced from ±30%) to avoid extreme swings.
    # A component needs +1.0% PnL delta to get +20% weight boost.
    pnl_adjustment = max(-0.20, min(0.20, delta_pnl / 5.0))
    wr_adjustment = max(-0.10, min(0.10, delta_wr))
    # Blend 70% PnL + 30% WR for final adjustment
    adjustment = 0.7 * pnl_adjustment + 0.3 * wr_adjustment
    suggested = base_weight * (1.0 + adjustment)

    return ComponentStats(
        present_count=len(present),
        present_wins=present_wins,
        absent_count=len(absent),
        absent_wins=absent_wins,
        present_wr=round(present_wr * 100, 1),
        absent_wr=round(absent_wr * 100, 1),
        delta_wr=round(delta_wr * 100, 1),
        present_pnl=round(present_pnl, 4),
        absent_pnl=round(absent_pnl, 4),
        delta_pnl=round(delta_pnl, 4),
        suggested_weight=round(suggested, 2),
    )


def _fetch_signals_for_weights(db: Session, max_samples: int, target_timeframe: str | None = None):
    """Fetch signals for adaptive weight recalibration.

    Data quality hierarchy (same as dataset_builder):
      - Real + same_tf = highest quality (weight 2.0)
      - Paper + same_tf = medium quality (weight 1.0)
      - Real + diff_tf = low quality (weight 0.3)
      - Paper + diff_tf = excluded (weight 0.0)

    If target_timeframe is None, computes GLOBAL weights using all real trades
    (paper gets reduced weight).
    """
    from app.models.ai_signal import AISignal
    from app.models.position import Position
    from app.models.bot_config import BotConfig
    from sqlalchemy import func

    # Build a map of signal_id → (is_real, signal_timeframe)
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
    all_rows = (
        db.query(AISignal)
        .filter(
            AISignal.outcome.in_([
                "SUCCESS",
                "FAILURE",
                "FAILURE_MAX_ADVERSE",
                "FAILURE_BEHAVIORAL",
            ]),
        )
        .filter(AISignal.features.isnot(None))
        .order_by(AISignal.resolved_at.desc().nullslast())
        .limit(max_samples)
        .all()
    )

    # Join with signal_meta to determine real/paper + timeframe match
    meta_rows = (
        db.query(
            signal_meta.c.signal_id,
            signal_meta.c.is_real,
            signal_meta.c.signal_timeframe,
        )
        .all()
    )
    meta_map = {}
    for r in meta_rows:
        meta_map[r.signal_id] = (r.is_real, r.signal_timeframe or "1h")

    filtered = []
    for s in all_rows:
        sid = str(s.id)
        if sid in meta_map:
            is_real, sig_tf = meta_map[sid]
            if target_timeframe is None:
                # Global: include all real (weight 2.0) and paper same weight as before
                s._aw_weight = 2.0 if is_real else 0.5
            else:
                same_tf = (sig_tf == target_timeframe)
                if is_real and same_tf:
                    s._aw_weight = 2.0
                elif not is_real and same_tf:
                    s._aw_weight = 1.0
                elif is_real and not same_tf:
                    s._aw_weight = 0.3
                else:
                    s._aw_weight = 0.0  # paper + diff_tf excluded
        else:
            # Signal without a position — treat as backtest data (low weight)
            s._aw_weight = 0.0 if target_timeframe else 0.1

        if s._aw_weight > 0:
            filtered.append(s)

    return filtered


def _compute_weights_for_rows(rows: list) -> dict[str, float]:
    """Compute adaptive weights from a list of signal rows (each with _aw_weight)."""
    if len(rows) < _MIN_SAMPLES_PER_COMPONENT * 3:
        return {}

    # Weighted baseline WR
    total_weight = sum(r._aw_weight for r in rows)
    win_weight = sum(r._aw_weight for r in rows if r.outcome == "SUCCESS")
    baseline = win_weight / total_weight if total_weight > 0 else 0.0

    # Component predicates based on features JSONB
    stats = {
        "structure_CHoCH": _component_stats(
            rows,
            lambda r: (r.features or {}).get("break_type") == "CHoCH",
            baseline, _BASELINE_WEIGHTS["structure_CHoCH"],
        ),
        "structure_BOS": _component_stats(
            rows,
            lambda r: (r.features or {}).get("break_type") == "BOS",
            baseline, _BASELINE_WEIGHTS["structure_BOS"],
        ),
        "trigger_OB": _component_stats(
            rows,
            lambda r: (r.features or {}).get("trigger") == "ob",
            baseline, _BASELINE_WEIGHTS["trigger_OB"],
        ),
        "trigger_FVG": _component_stats(
            rows,
            lambda r: (r.features or {}).get("trigger") == "fvg",
            baseline, _BASELINE_WEIGHTS["trigger_FVG"],
        ),
        "fvg_context": _component_stats(
            rows,
            lambda r: ((r.features or {}).get("fvg_aligned_count") or 0) >= 2,
            baseline, _BASELINE_WEIGHTS["fvg_context"],
        ),
        "sweep": _component_stats(
            rows,
            lambda r: (r.features or {}).get("sweep_detected") is True,
            baseline, _BASELINE_WEIGHTS["sweep"],
        ),
        "pd_array": _component_stats(
            rows,
            lambda r: _pd_correct(r),
            baseline, _BASELINE_WEIGHTS["pd_array"],
        ),
        "killzone": _component_stats(
            rows,
            lambda r: (r.features or {}).get("killzone") is not None,
            baseline, _BASELINE_WEIGHTS["killzone"],
        ),
    }

    new_weights: dict[str, float] = {}
    for key, st in stats.items():
        if st.present_count < _MIN_SAMPLES_PER_COMPONENT:
            logger.warning(
                f"[AdaptiveWeights] {key}: only {st.present_count} samples — keeping baseline"
            )
            new_weights[key] = _BASELINE_WEIGHTS[key]
        else:
            new_weights[key] = st.suggested_weight
            logger.info(
                f"[AdaptiveWeights] {key}: WR {st.present_wr}% vs {st.absent_wr}% "
                f"PnL {st.present_pnl:+.4f}% vs {st.absent_pnl:+.4f}% "
                f"(delta {st.delta_pnl:+.4f}%) → weight {_BASELINE_WEIGHTS[key]} → {st.suggested_weight}"
            )

    # Normalize so that max trending score (CHoCH + OB + 3×FVG + sweep + P/D + killzone) = 100
    max_trending = (
        new_weights["structure_CHoCH"] +
        new_weights["trigger_OB"] +
        3 * new_weights["fvg_context"] +
        new_weights["sweep"] +
        new_weights["pd_array"] +
        new_weights["killzone"]
    )
    if max_trending > 0:
        factor = 100.0 / max_trending
        for key in new_weights:
            new_weights[key] = round(new_weights[key] * factor, 2)

    return new_weights


def recalibrate_weights(db: Session, max_samples: int = 5000) -> dict:
    """
    Recalibrate adaptive weights from resolved signal history.

    Computes BOTH global weights (all real trades) AND per-timeframe weights
    (real + paper_same_tf for each timeframe). This lets the confluence engine
    use timeframe-specific weights: a CHoCH in 15m may score differently than
    a CHoCH in 1d.

    Paper trades from the SAME timeframe are included with reduced weight (1.0
    vs 2.0 for real), so paper testing on 1d contributes to 1d weight calibration.
    """
    # ── Global weights ──
    global_rows = _fetch_signals_for_weights(db, max_samples, target_timeframe=None)
    global_weights = _compute_weights_for_rows(global_rows)

    if not global_weights:
        logger.warning(
            f"[AdaptiveWeights] Insufficient samples ({len(global_rows)}) for global recalibration. "
            f"Minimum: {_MIN_SAMPLES_PER_COMPONENT * 3}"
        )
        return {}

    logger.info(f"[AdaptiveWeights] Global baseline computed from {len(global_rows)} signals")

    # ── Per-timeframe weights ──
    from app.core.constants import VALID_TIMEFRAMES
    by_timeframe: dict[str, dict] = {}

    for tf in VALID_TIMEFRAMES:
        tf_rows = _fetch_signals_for_weights(db, max_samples, target_timeframe=tf)
        if len(tf_rows) >= _MIN_SAMPLES_PER_COMPONENT * 3:
            tf_weights = _compute_weights_for_rows(tf_rows)
            if tf_weights:
                by_timeframe[tf] = tf_weights
                logger.info(
                    f"[AdaptiveWeights] {tf}: calibrated from {len(tf_rows)} signals "
                    f"(CHoCH={tf_weights.get('structure_CHoCH', 0):.1f}, "
                    f"sweep={tf_weights.get('sweep', 0):.1f})"
                )
        else:
            logger.debug(
                f"[AdaptiveWeights] {tf}: insufficient data ({len(tf_rows)} signals), skipping"
            )

    payload = {
        "calibrated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "baseline_wr": 0.0,  # computed per-segment now
        "sample_size": len(global_rows),
        "global": global_weights,
        "by_timeframe": by_timeframe,
    }

    # Persist
    _WEIGHT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_WEIGHT_PATH, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info(f"[AdaptiveWeights] Saved global + {len(by_timeframe)} timeframes to {_WEIGHT_PATH}")

    return payload


def _pd_correct(row: AISignal) -> bool:
    """Check if P/D position is favorable for the signal direction."""
    f = row.features or {}
    bias = f.get("bias", "")
    pd_pos = f.get("pd_position", 0.5)
    if bias == "bull":
        return pd_pos < 0.5
    elif bias == "bear":
        return pd_pos > 0.5
    return False


# ═══════════════════════════════════════════════════════════
# Contraejemplo-Driven Feature Calibration (CDFC)
# ═══════════════════════════════════════════════════════════

class ContraejemploCalibrator:
    """Analiza señales FALLURE recientes y penaliza features que mintieron.

    Wrapper stateless — se instancia por recalibración, no persiste entre
    ejecuciones. El cooldown es en-memoria (no persiste).
    """

    COOLDOWN_PERIODS = 25
    EXPECTED_CORRELATION = {
        "sweep_bool": "positive",
        "trigger_fvg": "positive",
        "fvg_aligned_count": "positive",
        "trigger_ob": "positive",
        "ob_distance_atr": "negative",
        "break_choch": "positive",
        "eq_highs_count": "negative",
        "eq_lows_count": "negative",
        "killzone_ny": "positive",
        "killzone_london": "positive",
        "volume_ratio": "positive",
        "spread_atr": "negative",
    }

    def __init__(self, db: Session):
        self.db = db
        self.cooldown: dict[str, int] = {}   # feature_regime -> remaining_periods
        self.weights_delta: dict[str, float] = {}

    def analyze_recent_failures(self, hours_back: int = 24) -> dict[str, float]:
        """Consulta DB por señales FAILURE recientes y acumula penalizaciones."""
        from app.models.ai_signal import AISignal
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

        rows = (
            self.db.query(AISignal)
            .filter(
                AISignal.outcome.in_(["FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL"]),
                AISignal.features.isnot(None),
                AISignal.resolved_at >= cutoff,
            )
            .all()
        )

        logger.info(f"[CDFC] Analyzing {len(rows)} recent failures…")

        for signal in rows:
            features = signal.features or {}
            regime = features.get("market_regime", "unknown")

            for feature, value in features.items():
                expected = self.EXPECTED_CORRELATION.get(feature)
                if not expected or expected == "contextual":
                    continue

                # Determinar si este feature fue "falso positivo de confianza"
                is_false_positive = False
                if expected == "positive" and isinstance(value, (int, float)) and value > 0.6:
                    is_false_positive = True
                elif expected == "negative" and isinstance(value, (int, float)) and value < 0.4:
                    is_false_positive = True

                if is_false_positive:
                    cooldown_key = f"{feature}_{regime}"
                    if self.cooldown.get(cooldown_key, 0) > 0:
                        continue

                    confidence = float(value) if expected == "positive" else (1.0 - float(value))
                    penalty = 0.04 * confidence  # max -4% por error
                    self.weights_delta[feature] = self.weights_delta.get(feature, 0.0) - penalty
                    self.cooldown[cooldown_key] = self.COOLDOWN_PERIODS

        logger.info(
            f"[CDFC] Penalties computed for {len(self.weights_delta)} features: "
            + ", ".join(f"{k}={v:.4f}" for k, v in self.weights_delta.items())
        )
        return self.weights_delta

    def apply_to_weights(self, base_weights: dict[str, float]) -> dict[str, float]:
        """Aplica penalizaciones acumuladas a pesos base con rate-limit ±10%."""
        result = dict(base_weights)

        for feature, delta in self.weights_delta.items():
            if feature in result:
                # Rate-limit ±10% como en tu lógica actual de seguridad
                capped_delta = max(-0.10, min(0.10, delta))
                result[feature] = max(0.35, min(1.5, result[feature] + capped_delta))

        # Recuperación gradual: features sin penalización reciente recuperan +0.8%
        for feature in result:
            if feature not in self.weights_delta:
                recent_penalty = any(
                    f.startswith(feature) for f in self.cooldown
                )
                if not recent_penalty:
                    result[feature] = min(1.5, result[feature] + 0.008)

        return result


def recalibrate_with_contraejemplos(db: Session, max_samples: int = 5000) -> dict:
    """Recalibrate adaptive weights: agregado + contraejemplos."""
    # 1. Tu lógica actual (estadística agregada por componente)
    payload = recalibrate_weights(db, max_samples=max_samples)

    if not payload or "global" not in payload:
        return payload

    # 2. Análisis de contraejemplos
    calibrator = ContraejemploCalibrator(db)
    calibrator.analyze_recent_failures(hours_back=24)

    global_weights = payload.get("global", {})
    final_global = calibrator.apply_to_weights(global_weights)

    # Re-normalizar para que max trending score = 100
    max_trending = (
        final_global.get("structure_CHoCH", 20.0)
        + final_global.get("trigger_OB", 15.0)
        + 3 * final_global.get("fvg_context", 4.0)
        + final_global.get("sweep", 18.0)
        + final_global.get("pd_array", 10.0)
        + final_global.get("killzone", 10.0)
    )
    if max_trending > 0:
        factor = 100.0 / max_trending
        for key in final_global:
            final_global[key] = round(final_global[key] * factor, 2)

    payload["global"] = final_global
    payload["by_ticker"] = {}  # placeholder si se extiende en futuro
    payload["calibrated_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    payload["cdf_applied"] = True
    payload["cdf_penalties"] = dict(calibrator.weights_delta)

    # Re-guardar
    _WEIGHT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_WEIGHT_PATH, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info(f"[AdaptiveWeights] Saved global + CDFC to {_WEIGHT_PATH}")

    return payload


def get_latest_calibration() -> dict | None:
    """Return the latest calibration payload if available."""
    if not _WEIGHT_PATH.exists():
        return None
    try:
        with open(_WEIGHT_PATH) as f:
            return json.load(f)
    except Exception:
        return None
