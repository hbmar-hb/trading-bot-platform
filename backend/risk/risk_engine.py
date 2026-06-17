"""Risk Engine — simplified to 3 multipliers max.

Evaluación 1: 6 multipliers = over-engineering.
Evaluación 2: Use calibrated confidence, not raw ensemble prob.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loguru import logger

RiskStatus = Literal["GREEN", "YELLOW", "RED"]

# ── Per-quality base sizes (arbitrary units, scaled by downstream) ───────────
_BASE_SIZE = {
    "STRONG": 100.0,
    "MODERATE": 50.0,
    "WEAK": 0.0,
}

# ── Calibrated confidence multipliers (linear by bands, NOT sigmoid) ─────────
# Evaluación 2: AUC 0.71 → confidences rarely >0.75. Sigmoid was utopian.
_CONF_MULTIPLIERS = [
    (0.0, 0.5, 0.0),    # < 0.5  → 0% sizing
    (0.5, 0.6, 0.3),    # 0.5-0.6 → 30% sizing
    (0.6, 0.7, 0.6),    # 0.6-0.7 → 60% sizing
    (0.7, 0.8, 0.85),   # 0.7-0.8 → 85% sizing
    (0.8, 1.0, 1.0),    # ≥ 0.8  → 100% sizing
]

_RISK_MULTIPLIERS: dict[RiskStatus, float] = {
    "GREEN": 1.0,
    "YELLOW": 0.5,
    "RED": 0.0,
}

# ── System-wide risk limits ──────────────────────────────────────────────────
_MAX_DAILY_DD_PCT = 5.0
_MAX_EXPOSURE_ABSOLUTE = 10000.0
_MAX_SLIPPAGE_BPS = 50.0


@dataclass(frozen=True)
class RiskAssessment:
    status: RiskStatus
    daily_drawdown_pct: float
    total_exposure: float
    avg_slippage_bps: float
    reasons: list[str]


class RiskEngine:
    """Unified risk engine with 3-multiplier sizing.

    Usage:
        engine = RiskEngine()
        status = engine.assess(positions, portfolio_value, avg_slippage_bps)
        size = engine.calculate_size("STRONG", 0.65, status.status)
    """

    def __init__(self):
        self.max_daily_dd = _MAX_DAILY_DD_PCT
        self.max_exposure = _MAX_EXPOSURE_ABSOLUTE
        self.max_slippage_bps = _MAX_SLIPPAGE_BPS

    # ── System assessment ─────────────────────────────────────────────────────

    def assess(
        self,
        positions: list,
        portfolio_value: float,
        avg_slippage_bps: float,
    ) -> RiskAssessment:
        """Assess overall system risk state."""
        reasons: list[str] = []
        status: RiskStatus = "GREEN"

        # Daily drawdown check
        daily_dd = self._daily_drawdown(portfolio_value)
        if daily_dd <= -self.max_daily_dd:
            status = "RED"
            reasons.append(f"daily_drawdown_{daily_dd:.1f}%_<=_-{self.max_daily_dd}%")
        elif daily_dd <= -self.max_daily_dd * 0.6:
            if status == "GREEN":
                status = "YELLOW"
            reasons.append(f"daily_drawdown_{daily_dd:.1f}%_elevated")

        # Total exposure check
        total_exposure = self._total_exposure(positions)
        if total_exposure >= self.max_exposure:
            status = "RED"
            reasons.append(f"total_exposure_{total_exposure:.0f}_>=_{self.max_exposure}")
        elif total_exposure >= self.max_exposure * 0.8:
            if status == "GREEN":
                status = "YELLOW"
            reasons.append(f"total_exposure_{total_exposure:.0f}_approaching_limit")

        # Slippage check
        if avg_slippage_bps > self.max_slippage_bps:
            if status == "GREEN":
                status = "YELLOW"
            reasons.append(f"avg_slippage_{avg_slippage_bps:.0f}bps_>{self.max_slippage_bps}bps")

        return RiskAssessment(
            status=status,
            daily_drawdown_pct=daily_dd,
            total_exposure=total_exposure,
            avg_slippage_bps=avg_slippage_bps,
            reasons=reasons,
        )

    # ── Per-trade sizing ──────────────────────────────────────────────────────

    def calculate_size(
        self,
        quality: str,
        calibrated_conf: float | None,
        risk_status: RiskStatus,
    ) -> float:
        """Calculate position size using exactly 3 multipliers.

        Args:
            quality: STRONG | MODERATE | WEAK
            calibrated_conf: Calibrated confidence from ensemble (0-1)
            risk_status: GREEN | YELLOW | RED

        Returns:
            Suggested size in arbitrary units (0 = no trade)
        """
        # Kill switch
        if risk_status == "RED":
            return 0.0

        # Base by quality
        base = _BASE_SIZE.get(quality, 0.0)
        if base == 0.0:
            return 0.0

        # Confidence multiplier (linear bands, not sigmoid)
        conf_mult = 0.0
        if calibrated_conf is not None:
            for lo, hi, mult in _CONF_MULTIPLIERS:
                if lo <= calibrated_conf < hi:
                    conf_mult = mult
                    break
            if calibrated_conf >= 0.8:
                conf_mult = 1.0

        # Risk state multiplier
        risk_mult = _RISK_MULTIPLIERS.get(risk_status, 0.0)

        # Evaluación 1: Only 3 multipliers
        size = base * conf_mult * risk_mult
        logger.debug(
            f"[RiskEngine] size={size:.2f} base={base} conf={calibrated_conf} "
            f"conf_mult={conf_mult} risk={risk_status} risk_mult={risk_mult}"
        )
        return round(size, 2)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _daily_drawdown(self, portfolio_value: float) -> float:
        """Calculate today's drawdown from daily high tracked in Redis."""
        from datetime import date
        from app.services.cache import sync_redis

        today = date.today().isoformat()
        redis_key = f"portfolio:daily_high:{today}"

        try:
            cached = sync_redis.get(redis_key)
            if cached:
                daily_high = float(cached)
            else:
                # First call today — seed with current portfolio value
                daily_high = portfolio_value
                sync_redis.set(redis_key, str(daily_high), ex=86400)

            # Update daily high if current value is higher
            if portfolio_value > daily_high:
                daily_high = portfolio_value
                sync_redis.set(redis_key, str(daily_high), ex=86400)

            if daily_high > 0:
                return ((portfolio_value - daily_high) / daily_high) * 100.0
        except Exception as e:
            logger.warning(f"[RiskEngine] _daily_drawdown Redis failed: {e}")

        return 0.0

    def _total_exposure(self, positions: list) -> float:
        """Sum of absolute notional exposure across all open positions."""
        total = 0.0
        for p in positions:
            entry = float(getattr(p, "entry_price", 0) or 0)
            qty = float(getattr(p, "quantity", 0) or 0)
            total += entry * qty
        return total


def quick_size(
    quality: str,
    calibrated_conf: float | None,
    risk_status: RiskStatus = "GREEN",
) -> float:
    """Convenience function for one-off sizing without instantiating RiskEngine."""
    engine = RiskEngine()
    return engine.calculate_size(quality, calibrated_conf, risk_status)
