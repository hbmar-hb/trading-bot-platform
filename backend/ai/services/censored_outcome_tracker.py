"""Censored Outcome Tracker — handles signals that never resolve within tracking window.

Evaluación 1 + 3 consensus:
- effective_label = 0.5 (neutral) — NEVER survival_prob
- sample_weight proportional to survival duration (0.1 → 0.3)
- Exclude PENDING completely from training
- Reject training if >30% of dataset is CENSORED
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from loguru import logger

MAX_TRACKING_HOURS = 72

OutcomeType = Literal["SUCCESS", "FAILURE", "CENSORED"]


@dataclass(frozen=True)
class CensoredOutcome:
    signal_id: str
    outcome: OutcomeType
    duration_hours: float
    effective_label: float  # Always 0.5 for CENSORED
    sample_weight: float    # 0.1 (new) → 0.3 (almost timeout)


class CensoredOutcomeTracker:
    """Process pending signals and produce censored outcomes when they time out.

    Usage:
        tracker = CensoredOutcomeTracker()
        outcome = tracker.process_single(signal, now=datetime.now(timezone.utc))
        if outcome:
            # Save to DB: outcome.outcome = "CENSORED", outcome.sample_weight
    """

    def __init__(self, max_tracking_hours: int = MAX_TRACKING_HOURS):
        self.max_tracking = max_tracking_hours

    def process_single(self, signal, now: datetime | None = None) -> CensoredOutcome | None:
        """Check if a single signal has exceeded max tracking time.

        Returns CensoredOutcome if timed out, None otherwise.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        if signal.outcome != "PENDING":
            return None

        duration = (now - signal.created_at).total_seconds() / 3600
        if duration <= self.max_tracking:
            return None

        # Evaluación 3: weight proportional to duration survived
        # More duration = more information = more weight (but always < 1.0)
        weight = min(0.1 + (duration / self.max_tracking) * 0.2, 0.3)

        return CensoredOutcome(
            signal_id=str(signal.id),
            outcome="CENSORED",
            duration_hours=round(duration, 2),
            effective_label=0.5,  # NEUTRAL — never survival_prob
            sample_weight=round(weight, 4),
        )

    def process_batch(self, pending_signals: list, now: datetime | None = None) -> list[CensoredOutcome]:
        """Process a batch of pending signals."""
        results = []
        for signal in pending_signals:
            outcome = self.process_single(signal, now)
            if outcome:
                results.append(outcome)
        return results


# ── Training set helpers ─────────────────────────────────────────────────────

def build_training_set(signals: list) -> tuple[list[dict], list[float], list[float]]:
    """Build X, y, weights from signals including CENSORED.

    Returns:
        (features_list, labels_list, weights_list)

    Rules:
    - SUCCESS/FAILURE → label 1/0, weight 1.0
    - CENSORED → label 0.5, weight = censored_weight (from features)
    - PENDING → excluded completely
    """
    X, y, weights = [], [], []
    censored_count = 0
    total_count = 0

    for s in signals:
        if not s.features:
            continue

        total_count += 1
        outcome = s.realistic_outcome

        if outcome is None:
            continue

        if outcome in ("SUCCESS", "FAILURE"):
            X.append(dict(s.features))
            y.append(1.0 if outcome == "SUCCESS" else 0.0)
            weights.append(1.0)
        elif outcome == "CENSORED":
            # Extract weight from features (set by outcome tracker)
            censored_weight = float(s.features.get("censored_weight", 0.2))
            X.append(dict(s.features))
            y.append(0.5)  # Neutral label
            weights.append(censored_weight)
            censored_count += 1
        # PENDING: excluded completely

    if total_count > 0 and censored_count / total_count > 0.30:
        logger.warning(
            f"[CensoredOutcome] Dataset has {censored_count}/{total_count} "
            f"({censored_count/total_count:.1%}) CENSORED signals. "
            f"Rejecting training — insufficient resolved data."
        )
        return [], [], []

    return X, y, weights


def check_censored_ratio(signals: list) -> dict:
    """Check if dataset has too many censored signals for reliable training."""
    total = len([s for s in signals if s.realistic_outcome is not None])
    censored = len([s for s in signals if s.realistic_outcome == "CENSORED"])
    if total == 0:
        return {"passes": False, "censored_ratio": 0.0, "reason": "no_signals"}
    ratio = censored / total
    return {
        "passes": ratio <= 0.30,
        "censored_ratio": round(ratio, 3),
        "censored_count": censored,
        "total_count": total,
        "reason": None if ratio <= 0.30 else f"censored_ratio_{ratio:.1%}_exceeds_30%",
    }
