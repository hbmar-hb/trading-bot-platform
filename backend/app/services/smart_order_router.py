"""Smart Order Router (SOR) — dynamic maker/taker decision.

Decides execution strategy based on:
  1. Spread vs ATR (wide spread → limit order for better fill)
  2. Signal staleness (stale → market order for speed)
  3. Position size vs average volume (large → TWAP consideration)
  4. Exchange maker rebates (prefer limit when feasible)

Strategies:
  - MARKET: immediate fill, taker fee
  - LIMIT_MAKER: post-only limit at bid/ask, maker rebate
  - TWAP: split large order over time (advisory — caller handles execution)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from loguru import logger


@dataclass(frozen=True)
class RouteDecision:
    strategy: Literal["MARKET", "LIMIT_MAKER", "TWAP"]
    price: Decimal | None
    """Suggested limit price for LIMIT_MAKER; None for MARKET."""
    slices: int
    """Number of TWAP slices (1 for non-TWAP)."""
    reason: str


# Thresholds
_SPREAD_ATR_THRESHOLD = 0.15      # If spread > 15% of ATR → try limit
_STALE_SECONDS_THRESHOLD = 120    # If signal older than 2min → market urgency
_TWAP_NOTIONAL_THRESHOLD = 5000   # If notional > $5k → suggest TWAP
_TWAP_SLICE_SIZE = 2500           # Target $2.5k per slice


def route_order(
    symbol: str,
    direction: str,
    quantity: Decimal,
    notional: float,
    entry_price: float,
    best_bid: float | None,
    best_ask: float | None,
    atr_value: float,
    signal_age_seconds: float,
    exchange_supports_maker: bool = True,
) -> RouteDecision:
    """Decide execution strategy for a new position.

    Args:
        symbol: trading pair
        direction: "long" or "short"
        quantity: position size in base asset
        notional: position size in quote asset (USDT)
        entry_price: expected entry price
        best_bid: current best bid (for limit pricing)
        best_ask: current best ask (for limit pricing)
        atr_value: ATR in price units
        signal_age_seconds: how old the signal is
        exchange_supports_maker: whether exchange has maker rebates

    Returns:
        RouteDecision with strategy, price, slices, reason
    """
    # ── 1. Urgency: stale signal → market ──────────────────────────────────
    if signal_age_seconds > _STALE_SECONDS_THRESHOLD:
        return RouteDecision(
            strategy="MARKET",
            price=None,
            slices=1,
            reason=f"stale_signal:{signal_age_seconds:.0f}s>{_STALE_SECONDS_THRESHOLD}s",
        )

    # ── 2. Size: large notional → suggest TWAP ─────────────────────────────
    if notional > _TWAP_NOTIONAL_THRESHOLD:
        slices = max(2, int(notional // _TWAP_SLICE_SIZE))
        return RouteDecision(
            strategy="TWAP",
            price=None,
            slices=slices,
            reason=f"large_size:${notional:.0f}>{_TWAP_NOTIONAL_THRESHOLD} slices={slices}",
        )

    # ── 3. Spread analysis ─────────────────────────────────────────────────
    if best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid
        spread_pct = (spread / entry_price) * 100 if entry_price > 0 else 0
        spread_atr_ratio = spread / atr_value if atr_value > 0 else 0

        # Wide spread relative to ATR → limit order can improve fill
        if spread_atr_ratio > _SPREAD_ATR_THRESHOLD and exchange_supports_maker:
            if direction == "long":
                # Post buy limit at best bid (maker)
                limit_price = Decimal(str(best_bid))
            else:
                # Post sell limit at best ask (maker)
                limit_price = Decimal(str(best_ask))

            return RouteDecision(
                strategy="LIMIT_MAKER",
                price=limit_price,
                slices=1,
                reason=f"wide_spread:{spread_atr_ratio:.2f}x_ATR pct={spread_pct:.3f}%",
            )

    # ── 4. Default: market order ───────────────────────────────────────────
    return RouteDecision(
        strategy="MARKET",
        price=None,
        slices=1,
        reason="default_market",
    )


async def get_current_bid_ask(exchange, symbol: str) -> tuple[float | None, float | None]:
    """Fetch best bid/ask from exchange order book.
    Returns (bid, ask) or (None, None) on failure.
    """
    try:
        # Try to get order book
        order_book = await exchange._client.fetch_order_book(symbol)
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])
        best_bid = float(bids[0][0]) if bids else None
        best_ask = float(asks[0][0]) if asks else None
        return best_bid, best_ask
    except Exception as exc:
        logger.warning(f"[SOR] Failed to fetch order book for {symbol}: {exc}")
        return None, None
