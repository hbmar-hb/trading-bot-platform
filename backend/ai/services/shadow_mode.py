"""Shadow Mode — evaluate candidate models without executing real trades.

Evaluación 1 + 2: Institutional standard. New model predicts alongside live model,
but no real trades are executed. Promote only if shadow consistently outperforms live.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
from loguru import logger

from app.services.cache import sync_redis

_SHADOW_KEY = "shadow_mode:predictions"
_EVALUATION_MIN_SIGNALS = 100
_EVALUATION_WINDOW_HOURS = 168  # 7 days
_PROMOTION_SHARPE_MULTIPLIER = 1.2
_MIN_SHARPE_FOR_PROMOTION = 0.5


@dataclass
class ShadowPrediction:
    signal_id: str
    timestamp: str
    live_prob: float
    shadow_prob: float
    actual_outcome: str | None = None
    pnl_pct: float | None = None


class ShadowDeployer:
    """Manage shadow deployment of candidate models.

    Usage:
        deployer = ShadowDeployer()
        # On each signal:
        deployer.record(signal_id, live_prob, shadow_prob)
        # After resolution:
        deployer.resolve(signal_id, outcome, pnl)
        # Evaluate:
        result = deployer.evaluate_promotion()
    """

    def __init__(self):
        self._key = _SHADOW_KEY

    def record(self, signal_id: str, live_prob: float, shadow_prob: float) -> None:
        """Record a new shadow prediction."""
        if not signal_id or signal_id == "None":
            return
        pred = ShadowPrediction(
            signal_id=signal_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            live_prob=live_prob,
            shadow_prob=shadow_prob,
        )
        try:
            existing = sync_redis.lrange(self._key, 0, -1)
            existing.append(json.dumps(asdict(pred)))
            # Keep only last 5000 predictions (FIFO)
            if len(existing) > 5000:
                existing = existing[-5000:]
            sync_redis.delete(self._key)
            for item in existing:
                sync_redis.rpush(self._key, item)
            sync_redis.expire(self._key, int(timedelta(days=14).total_seconds()))
        except Exception as exc:
            logger.warning(f"[ShadowMode] Failed to record prediction: {exc}")

    def resolve(self, signal_id: str, outcome: str, pnl_pct: float | None) -> None:
        """Update a prediction with its actual outcome."""
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
            logger.warning(f"[ShadowMode] Failed to resolve prediction: {exc}")

    def evaluate_promotion(self) -> dict:
        """Evaluate whether shadow model should be promoted to live.

        Returns:
            {
                "promote": bool,
                "shadow_sharpe": float,
                "live_sharpe": float,
                "n_signals": int,
                "reason": str,
            }
        """
        try:
            items = sync_redis.lrange(self._key, 0, -1)
            predictions = [json.loads(item) for item in items]
        except Exception as exc:
            logger.warning(f"[ShadowMode] Failed to load predictions: {exc}")
            return {
                "promote": False,
                "shadow_sharpe": 0.0,
                "live_sharpe": 0.0,
                "n_signals": 0,
                "reason": "load_error",
            }

        # Filter resolved predictions within evaluation window
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_EVALUATION_WINDOW_HOURS)).isoformat()
        resolved = [
            p for p in predictions
            if p.get("actual_outcome") and p["timestamp"] >= cutoff
        ]

        if len(resolved) < _EVALUATION_MIN_SIGNALS:
            return {
                "promote": False,
                "shadow_sharpe": 0.0,
                "live_sharpe": 0.0,
                "n_signals": len(resolved),
                "reason": f"insufficient_signals: {len(resolved)} < {_EVALUATION_MIN_SIGNALS}",
            }

        # Simulate returns: trade if prob >= 0.5 (i.e. model thinks it's a success)
        shadow_returns = []
        live_returns = []
        for p in resolved:
            pnl = p.get("pnl_pct", 0) or 0
            if p["shadow_prob"] >= 0.5:
                shadow_returns.append(pnl)
            if p["live_prob"] >= 0.5:
                live_returns.append(pnl)

        shadow_sharpe = self._calculate_sharpe(shadow_returns)
        live_sharpe = self._calculate_sharpe(live_returns)

        if shadow_sharpe > live_sharpe * _PROMOTION_SHARPE_MULTIPLIER and shadow_sharpe > _MIN_SHARPE_FOR_PROMOTION:
            logger.info(
                f"[ShadowMode] PROMOTION recommended: "
                f"shadow_sharpe={shadow_sharpe:.3f} live_sharpe={live_sharpe:.3f} "
                f"n={len(resolved)}"
            )
            return {
                "promote": True,
                "shadow_sharpe": round(shadow_sharpe, 3),
                "live_sharpe": round(live_sharpe, 3),
                "n_signals": len(resolved),
                "reason": "shadow_outperforms_live",
            }

        return {
            "promote": False,
            "shadow_sharpe": round(shadow_sharpe, 3),
            "live_sharpe": round(live_sharpe, 3),
            "n_signals": len(resolved),
            "reason": f"shadow_sharpe={shadow_sharpe:.3f}_not>_live*{ _PROMOTION_SHARPE_MULTIPLIER }",
        }

    def clear(self) -> None:
        """Clear all shadow predictions."""
        try:
            sync_redis.delete(self._key)
            logger.info("[ShadowMode] Predictions cleared")
        except Exception as exc:
            logger.warning(f"[ShadowMode] Failed to clear predictions: {exc}")

    @staticmethod
    def _calculate_sharpe(returns: list[float]) -> float:
        """Calculate annualized Sharpe from returns."""
        if len(returns) < 5:
            return 0.0
        mean_r = np.mean(returns)
        std_r = np.std(returns, ddof=1)
        if std_r == 0:
            return 0.0
        return float(mean_r / std_r * np.sqrt(252))


# ── Convenience functions ────────────────────────────────────────────────────

def record_shadow(signal_id: str, live_prob: float, shadow_prob: float) -> None:
    """One-liner to record a shadow prediction."""
    ShadowDeployer().record(signal_id, live_prob, shadow_prob)


def evaluate_shadow() -> dict:
    """One-liner to evaluate shadow mode."""
    return ShadowDeployer().evaluate_promotion()
