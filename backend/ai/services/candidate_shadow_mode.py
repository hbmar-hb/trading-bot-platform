"""48-hour shadow mode for candidate model evaluation (Fase D).

Records live vs candidate predictions and, once signals resolve, evaluates
whether the candidate should be promoted using their actual realised PnL.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from loguru import logger

from app.services.cache import sync_redis

_SHADOW_KEY = "shadow_mode:candidate_predictions"
_EVALUATION_WINDOW_HOURS = 48
_EVALUATION_MIN_SIGNALS = 30
_PROMOTION_SHARPE_MULTIPLIER = 1.2
_MIN_SHARPE_FOR_PROMOTION = 0.5


@dataclass
class CandidatePrediction:
    signal_id: str
    timestamp: str
    live_prob: float
    candidate_prob: float
    actual_outcome: str | None = None
    pnl_pct: float | None = None


class CandidateShadowDeployer:
    def __init__(self):
        self._key = _SHADOW_KEY

    def record(self, signal_id: str, live_prob: float, candidate_prob: float) -> None:
        if not signal_id or signal_id == "None":
            return
        pred = CandidatePrediction(
            signal_id=signal_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            live_prob=live_prob,
            candidate_prob=candidate_prob,
        )
        try:
            existing = sync_redis.lrange(self._key, 0, -1)
            existing.append(json.dumps(asdict(pred)))
            if len(existing) > 5000:
                existing = existing[-5000:]
            sync_redis.delete(self._key)
            for item in existing:
                sync_redis.rpush(self._key, item)
            sync_redis.expire(self._key, int(timedelta(days=14).total_seconds()))
        except Exception as exc:
            logger.warning(f"[CandidateShadow] Failed to record: {exc}")

    def resolve(self, signal_id: str, outcome: str, pnl_pct: float | None) -> None:
        """Update a prediction with its actual outcome and PnL."""
        try:
            items = sync_redis.lrange(self._key, 0, -1)
            updated = []
            for item in items:
                pred = json.loads(item)
                if pred["signal_id"] == signal_id:
                    pred["actual_outcome"] = outcome
                    pred["pnl_pct"] = pnl_pct
                updated.append(json.dumps(pred))
            sync_redis.delete(self._key)
            for item in updated:
                sync_redis.rpush(self._key, item)
        except Exception as exc:
            logger.warning(f"[CandidateShadow] Failed to resolve {signal_id}: {exc}")

    def _parse_predictions(self) -> list[CandidatePrediction]:
        try:
            raw = sync_redis.lrange(self._key, 0, -1)
        except Exception as exc:
            logger.warning(f"[CandidateShadow] Failed to read redis: {exc}")
            return []

        preds: list[CandidatePrediction] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_EVALUATION_WINDOW_HOURS)
        for item in raw:
            try:
                d = json.loads(item)
                ts = datetime.fromisoformat(d["timestamp"])
                if ts >= cutoff:
                    preds.append(CandidatePrediction(**d))
            except Exception:
                continue
        return preds

    @staticmethod
    def _calculate_sharpe(returns: list[float]) -> float:
        if len(returns) < 2:
            return 0.0
        mean = statistics.mean(returns)
        std = statistics.stdev(returns)
        if std == 0:
            return 0.0
        # Returns are per-signal; annualise assuming ~252 independent signals/day is
        # not meaningful.  Use sqrt scaling by number of observations to keep the
        # metric comparable across windows of different size.
        return mean / std * math.sqrt(max(len(returns), 1))

    def evaluate_promotion(self) -> dict:
        """Evaluate whether the candidate model should replace the live model.

        Only resolved predictions with a real PnL are used.  The same PnL is
        applied to both live and candidate according to whether each model would
        have taken the trade (prob >= 0.5), keeping the comparison fair.
        """
        preds = self._parse_predictions()
        resolved = [p for p in preds if p.pnl_pct is not None]
        n = len(resolved)

        if n < _EVALUATION_MIN_SIGNALS:
            return {
                "promote": False,
                "reason": f"insufficient_signals ({n}/{_EVALUATION_MIN_SIGNALS})",
                "candidate_sharpe": 0.0,
                "live_sharpe": 0.0,
                "n_signals": n,
                "n_resolved": n,
            }

        live_returns: list[float] = []
        candidate_returns: list[float] = []
        for p in resolved:
            pnl = float(p.pnl_pct)
            if p.live_prob >= 0.5:
                live_returns.append(pnl)
            if p.candidate_prob >= 0.5:
                candidate_returns.append(pnl)

        live_sharpe = self._calculate_sharpe(live_returns)
        candidate_sharpe = self._calculate_sharpe(candidate_returns)

        promote = (
            candidate_sharpe > live_sharpe * _PROMOTION_SHARPE_MULTIPLIER
            and candidate_sharpe > _MIN_SHARPE_FOR_PROMOTION
        )

        return {
            "promote": promote,
            "candidate_sharpe": round(candidate_sharpe, 3),
            "live_sharpe": round(live_sharpe, 3),
            "n_signals": n,
            "n_resolved": n,
            "reason": (
                "candidate_outperforms_live" if promote
                else "candidate_does_not_outperform_live"
            ),
        }

    def clear(self) -> None:
        try:
            sync_redis.delete(self._key)
        except Exception as exc:
            logger.warning(f"[CandidateShadow] Failed to clear: {exc}")


def record_candidate_shadow(signal_id: str, live_prob: float, candidate_prob: float) -> None:
    CandidateShadowDeployer().record(signal_id, live_prob, candidate_prob)


def resolve_candidate_shadow(signal_id: str, outcome: str, pnl_pct: float | None) -> None:
    CandidateShadowDeployer().resolve(signal_id, outcome, pnl_pct)


def evaluate_candidate_shadow() -> dict:
    return CandidateShadowDeployer().evaluate_promotion()
