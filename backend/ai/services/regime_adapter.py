"""Regime Adapter — adjusts thresholds post-prediction, NOT as model features.

Evaluación 1: Regime as a feature = instability. Use ONLY in post-processing
for threshold/sizing adjustments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RegimeType = Literal["trending_up", "trending_down", "ranging", "volatile", "unknown"]


@dataclass(frozen=True)
class RegimeAdjustment:
    score_multiplier: float
    prob_multiplier: float
    description: str


class RegimeAdapter:
    """Adjust quality thresholds and sizing based on detected market regime.

    This operates AFTER the ML ensemble prediction, never before.
    The model sees pure structural features; regime adjustments are
    applied only to the final gate thresholds.
    """

    _MULTIPLIERS: dict[RegimeType, dict[str, float]] = {
        "trending_up":   {"score": 1.0, "prob": 1.0},
        "trending_down": {"score": 1.0, "prob": 1.0},
        "ranging":       {"score": 0.85, "prob": 0.85},   # More permissive in range
        "volatile":      {"score": 1.1, "prob": 1.15},    # Slightly stricter in volatile
        "unknown":       {"score": 1.0, "prob": 1.0},
    }

    # Normalise regime names coming from detect_regime (uppercase / variants)
    # to the canonical keys used in _MULTIPLIERS.
    _REGIME_MAP: dict[str, RegimeType] = {
        "ranging": "ranging",
        "compression": "ranging",
        "volatile_spike": "volatile",
        "trending_bull": "trending_up",
        "trending_bear": "trending_down",
        "unknown": "unknown",
    }

    @classmethod
    def _canonical_regime(cls, regime: str) -> RegimeType:
        return cls._REGIME_MAP.get(regime.lower(), "unknown")

    @classmethod
    def adjust_thresholds(
        cls,
        base_score_threshold: float,
        base_prob_threshold: float,
        regime: RegimeType,
    ) -> RegimeAdjustment:
        """Return adjusted thresholds for a given regime."""
        canonical = cls._canonical_regime(regime)
        m = cls._MULTIPLIERS.get(canonical, cls._MULTIPLIERS["unknown"])
        return RegimeAdjustment(
            score_multiplier=m["score"],
            prob_multiplier=m["prob"],
            description=f"regime={regime}→{canonical}: score×{m['score']:.1f}, prob×{m['prob']:.1f}",
        )

    @classmethod
    def apply_to_signal(
        cls,
        score: float,
        success_prob: float | None,
        regime: RegimeType,
        base_score_threshold: float = 40.0,
        base_prob_threshold: float = 0.40,
    ) -> tuple[bool, str]:
        """Check if a signal passes regime-adjusted thresholds.

        Returns (passes, reason).
        """
        adj = cls.adjust_thresholds(base_score_threshold, base_prob_threshold, regime)

        adjusted_score_threshold = base_score_threshold * adj.score_multiplier
        adjusted_prob_threshold = base_prob_threshold * adj.prob_multiplier

        if score < adjusted_score_threshold:
            return False, f"score_{score:.1f}_<_{adjusted_score_threshold:.1f} ({adj.description})"

        if success_prob is not None and success_prob < adjusted_prob_threshold:
            return False, f"success_prob_{success_prob:.3f}_<_{adjusted_prob_threshold:.3f} ({adj.description})"

        return True, f"passed ({adj.description})"
