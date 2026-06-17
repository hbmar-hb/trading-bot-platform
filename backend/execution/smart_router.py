"""Smart Order Router — minimum viable execution layer.

Evaluación 2: "No veo una capa robusta de execution."
Decides order type based on market regime, spread, and signal confidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


OrderType = Literal["MARKET", "LIMIT", "STOP_LIMIT"]
TimeInForce = Literal["GTC", "IOC", "FOK"]


@dataclass(frozen=True)
class OrderInstruction:
    type: OrderType
    price: float | None
    time_in_force: TimeInForce
    post_only: bool
    slippage_accepted: float | None
    detail: str


class SmartOrderRouter:
    """Route a signal to the appropriate order type and parameters."""

    _SPREAD_LIMIT_PCT = 0.005   # 0.5% spread → force limit order
    _CONFIDENCE_MARKET = 0.80   # >80% confidence → market order acceptable
    _LIMIT_OFFSET_BPS = 20.0    # 20 bps better price for limit in volatile regime

    @classmethod
    def route(
        cls,
        entry_price: float,
        direction: str,
        confidence: float,
        regime: str,
        spread_pct: float,
    ) -> OrderInstruction:
        """
        Decide order type and parameters.

        Args:
            entry_price: target entry price from signal
            direction: "long" or "short"
            confidence: calibrated confidence (0-1)
            regime: market regime string (volatile, trending_up, etc.)
            spread_pct: current spread as fraction of price (0.001 = 0.1%)
        """
        is_volatile = regime == "volatile" or spread_pct > cls._SPREAD_LIMIT_PCT

        if is_volatile:
            # Volatile / wide spread: limit order with offset for price improvement
            offset = 1 - (cls._LIMIT_OFFSET_BPS / 10_000)
            price = entry_price * offset if direction == "long" else entry_price / offset
            return OrderInstruction(
                type="LIMIT",
                price=round(price, 8),
                time_in_force="GTC",
                post_only=True,
                slippage_accepted=None,
                detail=f"volatile/regime={regime}/spread={spread_pct:.3%}: LIMIT @{price:.6f} (post-only)",
            )

        if confidence > cls._CONFIDENCE_MARKET:
            # High confidence, tight spread: accept market order for fast fill
            return OrderInstruction(
                type="MARKET",
                price=None,
                time_in_force="IOC",
                post_only=False,
                slippage_accepted=0.001,  # 10 bps accepted
                detail=f"high_conf={confidence:.2f}: MARKET (10bps slippage accepted)",
            )

        # Default: limit order at signal price for execution control
        return OrderInstruction(
            type="LIMIT",
            price=round(entry_price, 8),
            time_in_force="IOC",
            post_only=False,
            slippage_accepted=None,
            detail=f"default: LIMIT @ {entry_price:.6f} (IOC)",
        )
