"""Execution Analytics — computes real-world execution quality per (ticker, timeframe).

Builds execution profiles from closed AI positions + exchange trades.
Used by the realistic outcome engine and the autonomous config recalibrator.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from loguru import logger
from sqlalchemy import text

from app.services.database import SessionLocal


def _normalize_ticker(ticker: str) -> str:
    """Convert CCXT symbol (e.g. BTC/USDT:USDT) to ai_signals ticker format (BTCUSDT)."""
    if "/" in ticker:
        base = ticker.split("/")[0]
    elif ":" in ticker:
        base = ticker.split(":")[0]
    else:
        base = ticker
    return base.upper() + "USDT"


@dataclass
class ExecutionProfile:
    """Real-world execution statistics for a given ticker/timeframe."""

    ticker: str
    timeframe: str
    sample_count: int = 0

    # Slippage / fill quality
    avg_entry_slippage_pct: float = 0.0          # fill worse than signal entry
    avg_sl_gap_pct: float = 0.0                  # SL executed worse than signal SL
    avg_tp_slippage_pct: float = 0.0             # TP executed worse than signal TP

    # Costs
    # Round-trip fee as a % of notional (e.g. 0.1 = 0.1% entry+exit combined).
    fee_rate: float = 0.1
    avg_funding_cost_pct: float = 0.0            # funding per hour / notional

    # Execution reliability
    gap_frequency: float = 0.0                   # % of SLs that gapped
    tp_wick_fill_rate: float = 0.75              # % of TPs that actually filled vs just wicked

    # Duration
    avg_bars_to_close: float = 0.0

    # Reliability flag
    is_reliable: bool = False

    def version(self) -> str:
        return f"{self.ticker}:{self.timeframe}:{self.sample_count}"


# Conservative defaults when no real data exists.
# These numbers assume a taker-fee exchange with moderate volatility.
# fee_rate is expressed as round-trip % of notional (entry + exit combined).

DEFAULT_PROFILE = ExecutionProfile(
    ticker="DEFAULT",
    timeframe="1h",
    sample_count=0,
    avg_entry_slippage_pct=0.04,
    avg_sl_gap_pct=0.20,
    avg_tp_slippage_pct=0.00,
    fee_rate=0.10,
    avg_funding_cost_pct=0.005,
    gap_frequency=0.15,
    tp_wick_fill_rate=0.70,
    avg_bars_to_close=5.0,
    is_reliable=False,
)


_MIN_SAMPLES_FOR_RELIABLE = 5
_LOOKBACK_DAYS = 30


def _blend_profiles(measured: ExecutionProfile, default: ExecutionProfile, weight: float) -> ExecutionProfile:
    """Blend a measured profile into a conservative default.

    weight = measured weight; (1 - weight) = default weight.
    Keeps measured values from dominating until enough samples exist.
    """
    w = max(0.0, min(1.0, weight))
    return ExecutionProfile(
        ticker=measured.ticker,
        timeframe=measured.timeframe,
        sample_count=measured.sample_count,
        avg_entry_slippage_pct=round(measured.avg_entry_slippage_pct * w + default.avg_entry_slippage_pct * (1 - w), 4),
        avg_sl_gap_pct=round(measured.avg_sl_gap_pct * w + default.avg_sl_gap_pct * (1 - w), 4),
        avg_tp_slippage_pct=round(measured.avg_tp_slippage_pct * w + default.avg_tp_slippage_pct * (1 - w), 4),
        fee_rate=round(measured.fee_rate * w + default.fee_rate * (1 - w), 5),
        avg_funding_cost_pct=round(measured.avg_funding_cost_pct * w + default.avg_funding_cost_pct * (1 - w), 5),
        gap_frequency=round(measured.gap_frequency * w + default.gap_frequency * (1 - w), 4),
        tp_wick_fill_rate=round(measured.tp_wick_fill_rate * w + default.tp_wick_fill_rate * (1 - w), 4),
        avg_bars_to_close=round(measured.avg_bars_to_close * w + default.avg_bars_to_close * (1 - w), 2),
        is_reliable=measured.sample_count >= _MIN_SAMPLES_FOR_RELIABLE,
    )


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator != 0 else 0.0


def _default_profile_for(ticker: str, timeframe: str) -> ExecutionProfile:
    """Return a conservative default profile with the requested ticker/timeframe."""
    return ExecutionProfile(
        ticker=ticker,
        timeframe=timeframe,
        sample_count=0,
        avg_entry_slippage_pct=DEFAULT_PROFILE.avg_entry_slippage_pct,
        avg_sl_gap_pct=DEFAULT_PROFILE.avg_sl_gap_pct,
        avg_tp_slippage_pct=DEFAULT_PROFILE.avg_tp_slippage_pct,
        fee_rate=DEFAULT_PROFILE.fee_rate,
        avg_funding_cost_pct=DEFAULT_PROFILE.avg_funding_cost_pct,
        gap_frequency=DEFAULT_PROFILE.gap_frequency,
        tp_wick_fill_rate=DEFAULT_PROFILE.tp_wick_fill_rate,
        avg_bars_to_close=DEFAULT_PROFILE.avg_bars_to_close,
        is_reliable=False,
    )


def get_execution_profile(ticker: str, timeframe: str) -> ExecutionProfile:
    """Return the execution profile for a given ticker/timeframe.

    Always starts from the measured profile. When sample count is below
    the reliability threshold, the measured profile is blended with the
    conservative default. No ticker/timeframe hash-based defaults.
    """
    measured = _build_profile_from_db(ticker, timeframe)
    if measured.sample_count == 0:
        return _default_profile_for(ticker, timeframe)
    if measured.sample_count >= _MIN_SAMPLES_FOR_RELIABLE:
        return measured
    weight = measured.sample_count / _MIN_SAMPLES_FOR_RELIABLE
    return _blend_profiles(measured, _default_profile_for(ticker, timeframe), weight)


def _build_profile_from_db(ticker: str, timeframe: str) -> ExecutionProfile:
    """Query closed AI positions and linked exchange trades to compute stats."""
    since = datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
    ticker_norm = _normalize_ticker(ticker)

    with SessionLocal() as db:
        # Query closed AI positions for this ticker/timeframe with signal metadata.
        # We join through extra_config->>'ai_signal_id' to AISignal.
        sql = text("""
            SELECT
                p.id AS position_id,
                p.entry_price,
                p.quantity,
                p.realized_pnl,
                p.extra_config,
                p.closed_at,
                p.opened_at,
                s.entry_price AS signal_entry_price,
                s.stop_loss AS signal_sl,
                s.take_profit_1 AS signal_tp1,
                s.timeframe AS signal_timeframe,
                s.score AS signal_score,
                s.quality_tier,
                s.anti_fake_status
            FROM positions p
            LEFT JOIN ai_signals s
                ON s.id = (p.extra_config->>'ai_signal_id')::uuid
            WHERE p.source = 'ai_bot'
              AND p.status = 'closed'
              AND p.closed_at >= :since
              AND s.ticker = :ticker
              AND s.timeframe = :timeframe
            ORDER BY p.closed_at DESC
            LIMIT 500
        """)

        rows = db.execute(
            sql, {"since": since, "ticker": ticker_norm, "timeframe": timeframe}
        ).mappings().all()

        if not rows:
            return ExecutionProfile(ticker=ticker, timeframe=timeframe, sample_count=0)

        # Aggregate stats
        entry_slippages: list[float] = []
        sl_gaps: list[float] = []
        tp_slippages: list[float] = []
        fees: list[float] = []
        notionals: list[float] = []
        gap_count = 0
        sl_count = 0
        tp_count = 0
        tp_filled_count = 0
        bars_list: list[float] = []

        for row in rows:
            pos_entry = float(row["entry_price"]) if row["entry_price"] else 0.0
            sig_entry = float(row["signal_entry_price"]) if row["signal_entry_price"] else 0.0
            sig_sl = float(row["signal_sl"]) if row["signal_sl"] else 0.0
            sig_tp1 = float(row["signal_tp1"]) if row["signal_tp1"] else 0.0
            qty = float(row["quantity"]) if row["quantity"] else 0.0
            realized = float(row["realized_pnl"]) if row["realized_pnl"] else 0.0
            extra = row["extra_config"] or {}

            # Notional (approximate using signal entry)
            notional = sig_entry * qty if sig_entry and qty else 0.0
            if notional > 0:
                notionals.append(notional)

            # 1. Entry slippage: how much worse was the fill vs signal entry?
            if sig_entry and pos_entry and sig_entry > 0:
                # For long: positive slippage means we entered worse (higher)
                side = extra.get("side", "long")
                if side == "long":
                    slippage = (pos_entry - sig_entry) / sig_entry * 100
                else:
                    slippage = (sig_entry - pos_entry) / sig_entry * 100
                entry_slippages.append(slippage)

            # 2. Risk / gap analysis
            risk_distance = float(extra.get("initial_risk_distance", 0)) or abs(sig_entry - sig_sl)
            if risk_distance and sig_entry:
                theoretical_loss_pct = risk_distance / sig_entry * 100
            else:
                theoretical_loss_pct = 0.0

            if realized < 0 and theoretical_loss_pct > 0:
                sl_count += 1
                actual_loss_pct = abs(realized) / notional * 100 if notional else 0.0
                if actual_loss_pct > theoretical_loss_pct * 1.2:
                    gap_count += 1
                    gap_pct = (actual_loss_pct - theoretical_loss_pct)
                    sl_gaps.append(gap_pct)

            # 3. TP analysis (winners)
            if realized > 0 and sig_tp1 and sig_entry:
                tp_count += 1
                theoretical_gain_pct = abs(sig_tp1 - sig_entry) / sig_entry * 100
                actual_gain_pct = realized / notional * 100 if notional else 0.0
                # If actual gain is within 20% of theoretical, assume TP filled
                if actual_gain_pct >= theoretical_gain_pct * 0.8:
                    tp_filled_count += 1
                    # Fase C: TP slippage can never be negative — a better-than-target
                    # fill is a data artefact, not a realistic execution assumption.
                    tp_slip = max(0.0, actual_gain_pct - theoretical_gain_pct)
                    tp_slippages.append(tp_slip)

            # 4. Bars to close (if we have opened_at and timeframe)
            opened = row["opened_at"]
            closed = row["closed_at"]
            tf = row["signal_timeframe"] or timeframe
            tf_min = _tf_to_minutes(tf)
            if opened and closed and tf_min > 0:
                mins = (closed - opened).total_seconds() / 60
                bars = mins / tf_min
                bars_list.append(bars)

        # Fase C: fetch ticker-wide fees from exchange_trades linked to closed AI positions.
        # We aggregate per position for notional and sum all linked trade fees per position
        # so the fee rate is a realistic round-trip % per ticker (not per timeframe).
        ticker_fee_sql = text("""
            SELECT
                COALESCE(SUM(sub.position_notional), 0) AS total_notional,
                COALESCE(SUM(sub.position_fee), 0) AS total_fee
            FROM (
                SELECT
                    p.id,
                    MAX(p.quantity * p.entry_price) AS position_notional,
                    COALESCE(SUM(et.fee), 0) AS position_fee
                FROM positions p
                LEFT JOIN ai_signals s ON s.id = (p.extra_config->>'ai_signal_id')::uuid
                LEFT JOIN exchange_trades et ON et.position_id::text = p.id::text
                WHERE p.source = 'ai_bot'
                  AND p.status = 'closed'
                  AND p.closed_at >= :since
                  AND s.ticker = :ticker
                GROUP BY p.id
            ) sub
        """)
        fee_row = db.execute(
            ticker_fee_sql, {"since": since, "ticker": ticker_norm}
        ).mappings().first()
        total_fee_ticker = float(fee_row["total_fee"] or 0) if fee_row else 0.0
        total_notional_ticker = float(fee_row["total_notional"] or 0) if fee_row else 0.0

    # Build profile
    sample_count = len(rows)
    total_notional = sum(notionals) if notionals else 0.0

    default = DEFAULT_PROFILE
    avg_entry_slippage = sum(entry_slippages) / len(entry_slippages) if entry_slippages else default.avg_entry_slippage_pct
    avg_sl_gap = sum(sl_gaps) / len(sl_gaps) if sl_gaps else default.avg_sl_gap_pct
    avg_tp_slippage = sum(tp_slippages) / len(tp_slippages) if tp_slippages else default.avg_tp_slippage_pct
    # Fase C: use ticker-wide measured fee rate; fall back to default only when no data.
    if total_notional_ticker > 0:
        fee_rate = (total_fee_ticker / total_notional_ticker) * 100.0
    else:
        fee_rate = default.fee_rate
    gap_freq = (gap_count / sl_count) if sl_count > 0 else default.gap_frequency
    tp_fill_rate = (tp_filled_count / tp_count) if tp_count > 0 else default.tp_wick_fill_rate
    avg_bars = sum(bars_list) / len(bars_list) if bars_list else default.avg_bars_to_close

    return ExecutionProfile(
        ticker=ticker,
        timeframe=timeframe,
        sample_count=sample_count,
        avg_entry_slippage_pct=round(avg_entry_slippage, 4),
        avg_sl_gap_pct=round(avg_sl_gap, 4),
        avg_tp_slippage_pct=round(avg_tp_slippage, 4),
        fee_rate=round(fee_rate, 5),
        avg_funding_cost_pct=default.avg_funding_cost_pct,
        gap_frequency=round(gap_freq, 4),
        tp_wick_fill_rate=round(tp_fill_rate, 4),
        avg_bars_to_close=round(avg_bars, 2),
        is_reliable=sample_count >= _MIN_SAMPLES_FOR_RELIABLE,
    )


def _tf_to_minutes(tf: str) -> int:
    mapping = {
        "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480,
        "12h": 720, "1d": 1440, "1w": 10080,
    }
    return mapping.get(tf, 60)


def get_profile_for_signal(ticker: str, timeframe: str) -> ExecutionProfile:
    """Public API: get execution profile, falling back to defaults when needed."""
    return get_execution_profile(ticker, timeframe)
