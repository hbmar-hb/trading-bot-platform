"""Kelly Criterion position sizing with safety caps.

Hierarchy: L1 Risk — applies after base sizing, before portfolio risk gate.
Uses historical performance metrics to compute optimal fraction of equity.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from loguru import logger


@dataclass(frozen=True)
class KellyResult:
    """Result of Kelly sizing computation."""

    sizing_multiplier: float
    """Multiplier to apply to base notional (0.0 = no position)."""

    kelly_fraction: float
    """Raw Kelly fraction (can be >1 or negative)."""

    half_kelly: float
    """Half-Kelly fraction (recommended for live trading)."""

    edge: float
    """Expected value per unit bet (p*b - q)."""

    capped_reason: str | None
    """Reason if fraction was capped."""


# Safety caps (hard limits regardless of Kelly output)
_MAX_KELLY_FRACTION = 0.05          # 5% of equity max (Half-Kelly) — default
_MAX_DRAWDOWN_PCT = 0.10             # Cap sizing when DD > 10% (spec says 10, not 15)
_MAX_ATR_PERCENTILE = 80             # High vol cap
_MIN_EDGE_FOR_TRADE = 0.005          # 0.5% edge minimum (relaxed for crypto signal flow)
_MIN_TRADES_FOR_KELLY = 20           # Need 20+ trades for reliable stats

# Regime-specific Kelly caps (Sprint 1.4 completion)
_REGIME_KELLY_CAP = {
    "RANGING":        0.05,   # Spec: ranging max 0.05
    "COMPRESSION":    0.05,   # Same as ranging — low conviction
    "VOLATILE_SPIKE": 0.03,   # Extreme vol — very conservative
    "TRENDING_BULL":  0.05,   # Standard
    "TRENDING_BEAR":  0.05,   # Standard
    "BTC_DOMINANCE":  0.045,  # Slightly reduced due to correlation risk
    "ALT_SEASON":     0.04,   # Reduced due to alt volatility
}


def _fetch_model_metrics(db, ticker: str, timeframe: str) -> dict | None:
    """Fetch historical performance metrics for a ticker/timeframe.

    Tries sources in order:
      1. Real positions SAME timeframe (highest quality)
      2. Paper positions SAME timeframe (medium quality)
      3. AI Signal realistic outcomes (fallback)
      4. Returns None if insufficient data.

    Paper trades from the SAME timeframe are now included because temporal
    dynamics (SL width, hold time, volatility) match the target timeframe.
    """
    from app.models.ai_signal import AISignal
    from app.models.position import Position
    from app.models.bot_config import BotConfig
    from sqlalchemy import func

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    # --- Source 1: Real + Paper SAME timeframe positions (last 90 days) ---
    # Join through extra_config->ai_signal_id to filter by signal timeframe
    pos_rows = (
        db.query(
            Position,
            BotConfig.paper_balance_id.is_(None).label("is_real"),
        )
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .join(
            AISignal,
            AISignal.id == func.cast(Position.extra_config["ai_signal_id"].astext, AISignal.id.type),
        )
        .filter(
            Position.symbol == ticker,
            Position.status == "closed",
            Position.closed_at.isnot(None),
            Position.closed_at >= cutoff,
            Position.realized_pnl.isnot(None),
            AISignal.timeframe == timeframe,
        )
        .all()
    )

    if pos_rows:
        # Weighted metrics: real=1.0, paper_same_tf=0.5
        weighted_wins = 0.0
        weighted_losses = 0.0
        weighted_pnl = []
        for p, is_real in pos_rows:
            weight = 1.0 if is_real else 0.5
            pnl = float(p.realized_pnl)
            # Calculate P&L % manually — Position model has no realized_pnl_pct column
            notional = float(p.entry_price) * float(p.quantity)
            if p.leverage and p.leverage > 0:
                notional = notional / float(p.leverage)
            pnl_pct = (pnl / notional * 100) if notional > 0 else 0.0
            if pnl > 0:
                weighted_wins += weight
            else:
                weighted_losses += weight
            weighted_pnl.append((pnl_pct, weight))

        total_weight = weighted_wins + weighted_losses
        if total_weight >= _MIN_TRADES_FOR_KELLY:
            win_rate = weighted_wins / total_weight
            wins = [(pnl, w) for pnl, w in weighted_pnl if pnl > 0]
            losses = [(pnl, w) for pnl, w in weighted_pnl if pnl <= 0]
            avg_win = sum(pnl * w for pnl, w in wins) / sum(w for _, w in wins) if wins else 0
            avg_loss = abs(sum(pnl * w for pnl, w in losses) / sum(w for _, w in losses)) if losses else 1.0
            payoff = avg_win / avg_loss if avg_loss > 0 else 1.0

            return {
                "win_rate": win_rate,
                "payoff_ratio": payoff,
                "avg_win_pct": avg_win,
                "avg_loss_pct": avg_loss,
                "sample_count": int(total_weight),
                "source": "positions_tf_weighted",
            }

    # --- Source 2: AI Signal realistic outcomes (last 60 days, same tf) ---
    cutoff_60 = datetime.now(timezone.utc) - timedelta(days=60)
    rows = (
        db.query(AISignal)
        .filter(
            AISignal.ticker == ticker,
            AISignal.timeframe == timeframe,
            AISignal.signal_time >= cutoff_60,
            AISignal.realistic_outcome.isnot(None),
        )
        .all()
    )

    if len(rows) >= _MIN_TRADES_FOR_KELLY:
        wins = [r for r in rows if r.realistic_outcome == "SUCCESS"]
        losses = [r for r in rows if r.realistic_outcome in ("FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL")]

        valid = wins + losses
        if not valid:
            return None

        win_rate = len(wins) / len(valid)
        avg_win = sum(r.realistic_pnl_pct for r in wins if r.realistic_pnl_pct) / len(wins) if wins else 0
        avg_loss = abs(sum(r.realistic_pnl_pct for r in losses if r.realistic_pnl_pct) / len(losses)) if losses else 1.0
        payoff = avg_win / avg_loss if avg_loss > 0 else 1.0

        return {
            "win_rate": win_rate,
            "payoff_ratio": payoff,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "sample_count": len(valid),
            "source": "ai_signals_realistic",
        }

    return None


def _get_current_drawdown(db, bot_id: str) -> float:
    """Estimate current drawdown from equity curve or open positions.

    Falls back to 0.0 if EquitySnapshot model is unavailable or
    insufficient data exists.
    """
    try:
        from app.models.equity_snapshot import EquitySnapshot
        from sqlalchemy import desc

        snaps = (
            db.query(EquitySnapshot)
            .filter(EquitySnapshot.bot_id == bot_id)
            .order_by(desc(EquitySnapshot.timestamp))
            .limit(30)
            .all()
        )

        if len(snaps) >= 5:
            peak = max(float(s.equity) for s in snaps)
            current = float(snaps[0].equity)
            if peak > 0:
                return (peak - current) / peak
    except Exception:
        pass

    # Fallback: compute drawdown from realized P&L of last 30 closed positions
    try:
        from app.models.position import Position
        from sqlalchemy import desc
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        rows = (
            db.query(Position)
            .filter(
                Position.bot_id == bot_id,
                Position.status == "closed",
                Position.realized_pnl.isnot(None),
                Position.closed_at >= cutoff,
            )
            .order_by(desc(Position.closed_at))
            .all()
        )
        if len(rows) >= 3:
            pnls = [float(p.realized_pnl or 0) for p in rows]
            cumulative = []
            running = 0.0
            for p in pnls:
                running += p
                cumulative.append(running)
            peak = max(cumulative)
            current = cumulative[-1]
            if peak > 0 and current < peak:
                return (peak - current) / peak
    except Exception:
        pass

    return 0.0


def compute_kelly_sizing(
    db,
    bot_id: str,
    ticker: str,
    timeframe: str,
    base_notional: float,
    equity: float,
    atr_percentile: float | None = None,
    regime: str | None = None,
    user_cfg: dict | None = None,
) -> KellyResult:
    """Compute Kelly-adjusted position size.

    Returns a KellyResult with sizing_multiplier to apply to base_notional.
    If edge is insufficient or data is sparse, returns conservative sizing.
    
    Args:
        regime: market regime name (e.g. RANGING, VOLATILE_SPIKE). Used for
                regime-specific Kelly caps.
    """
    metrics = _fetch_model_metrics(db, ticker, timeframe)

    if metrics is None:
        # Insufficient data — use conservative default (1.0, no adjustment)
        logger.info(
            f"[KELLY] {ticker}/{timeframe}: insufficient data "
            f"(<{_MIN_TRADES_FOR_KELLY} trades), using base sizing"
        )
        return KellyResult(
            sizing_multiplier=1.0,
            kelly_fraction=0.0,
            half_kelly=0.0,
            edge=0.0,
            capped_reason="insufficient_data",
        )

    p = metrics["win_rate"]
    b = metrics["payoff_ratio"]
    q = 1.0 - p

    # Edge = expected value per unit bet
    edge = p * b - q

    # Kelly fraction: f* = (p*b - q) / b
    if b <= 0:
        kelly_fraction = 0.0
    else:
        kelly_fraction = edge / b

    # Half-Kelly for live trading (reduces variance)
    half_kelly = kelly_fraction * 0.5

    # Convert fraction to notional multiplier
    # half_kelly is fraction of equity, base_notional may be % of equity or fixed
    # We express sizing_multiplier as: kelly_notional / base_notional
    if base_notional <= 0 or equity <= 0:
        sizing_multiplier = 0.0
    else:
        kelly_notional = equity * half_kelly
        sizing_multiplier = kelly_notional / base_notional

    capped_reason = None

    # --- Safety Caps ---

    # Apply per-bot calibration multiplier to edge threshold
    edge_mult = float(user_cfg.get("kelly_edge_multiplier", 1.0)) if user_cfg else 1.0
    effective_min_edge = _MIN_EDGE_FOR_TRADE * edge_mult

    # 1. Minimum edge gate — reduce sizing instead of blocking when edge is marginal
    if edge < effective_min_edge:
        if edge > 0:
            sizing_multiplier *= max(0.25, edge / effective_min_edge)
            capped_reason = f"edge_low_reduced:{edge:.4f}(th={effective_min_edge:.4f})"
            logger.info(
                f"[KELLY] {ticker}/{timeframe}: edge {edge:.4f} < {effective_min_edge:.4f}, "
                f"REDUCING sizing to {sizing_multiplier:.2f}x instead of blocking"
            )
        else:
            sizing_multiplier = 0.0
            capped_reason = f"edge_negative:{edge:.4f}"
            logger.warning(
                f"[KELLY] {ticker}/{timeframe}: edge {edge:.4f} <= 0, BLOCKING position"
            )
            return KellyResult(
                sizing_multiplier=sizing_multiplier,
                kelly_fraction=kelly_fraction,
                half_kelly=half_kelly,
                edge=edge,
                capped_reason=capped_reason,
            )

    # 2. Max fraction cap (regime-specific or default 5%)
    regime_cap = _REGIME_KELLY_CAP.get(regime, _MAX_KELLY_FRACTION) if regime else _MAX_KELLY_FRACTION
    max_notional = equity * regime_cap
    if kelly_notional > max_notional:
        sizing_multiplier = max_notional / base_notional
        capped_reason = f"max_fraction:{regime_cap:.2%}({regime or 'default'})"

    # 3. Drawdown cap (>10% per spec, was 15%)
    dd = _get_current_drawdown(db, bot_id)
    if dd > _MAX_DRAWDOWN_PCT:
        sizing_multiplier *= 0.5
        capped_reason = (capped_reason or "") + f"|drawdown_cap:{dd:.2%}(>10%)"

    # 4. High volatility cap (ATR > p80) — Sprint 1.4: more restrictive
    if atr_percentile is not None and atr_percentile > _MAX_ATR_PERCENTILE:
        sizing_multiplier *= 0.25  # Was 0.5, now 0.25 as per spec
        capped_reason = (capped_reason or "") + f"|vol_cap:p{atr_percentile:.0f}->0.25x"

    # 5. Never exceed 2x base sizing (Kelly shouldn't increase size)
    sizing_multiplier = min(sizing_multiplier, 2.0)

    # 6. Never go negative
    sizing_multiplier = max(sizing_multiplier, 0.0)

    logger.info(
        f"[KELLY] {ticker}/{timeframe}: win_rate={p:.2%} payoff={b:.2f} "
        f"edge={edge:.4f} half_kelly={half_kelly:.4f} "
        f"mult={sizing_multiplier:.2f} source={metrics['source']} "
        f"n={metrics['sample_count']}"
        + (f" cap={capped_reason}" if capped_reason else "")
    )

    return KellyResult(
        sizing_multiplier=sizing_multiplier,
        kelly_fraction=kelly_fraction,
        half_kelly=half_kelly,
        edge=edge,
        capped_reason=capped_reason,
    )


# Import here to avoid circular import at module level
from datetime import datetime, timezone, timedelta  # noqa: E402
