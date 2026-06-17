"""Causal Feature Builder — eliminates execution-lag leakage.

Evaluación 3 identified: a 1-second cutoff is insufficient for real-world latency.
This builder uses a dynamic buffer based on measured system latency (p95 of recent
real trades). If any historical feature cannot be built causally, the signal is
rejected — never imputed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import text

from app.services.database import SessionLocal

# ── Constants ────────────────────────────────────────────────────────────────
_MIN_SAMPLES_FOR_FEATURE = 15
_DEFAULT_LATENCY_MS = 200.0          # Fallback if no real trade data
_MIN_CUTOFF_BUFFER_MS = 500.0        # Absolute floor
_SAFETY_MARGIN_S = 1.0               # Additional 1s safety
_RECENT_TRADE_BUFFER_MIN = 5         # Buffer for potentially-open trades
_LOOKBACK_DAYS = 30                  # How far back to query for historical features


@dataclass(frozen=True)
class CausalFeatures:
    """Execution-quality features built with causal cutoffs."""

    tp_fill_rate_30d: float | None
    avg_slippage_30d: float | None
    gap_frequency_90d: float | None
    fee_rate: float | None

    @property
    def is_complete(self) -> bool:
        """All features must be present — None means rejection."""
        return all(
            v is not None
            for v in [self.tp_fill_rate_30d, self.avg_slippage_30d,
                      self.gap_frequency_90d, self.fee_rate]
        )


class CausalFeatureBuilder:
    """Build execution-quality features with causal cutoffs.

    Usage:
        builder = CausalFeatureBuilder()
        features = builder.build("BTCUSDT", signal_time)
        if not features.is_complete:
            reject_signal("insufficient_causal_data")
    """

    def __init__(self, db_session_factory=SessionLocal):
        self._db_factory = db_session_factory
        self._latency_ms = self._measure_system_latency()
        self.cutoff_buffer = timedelta(
            milliseconds=max(self._latency_ms * 2, _MIN_CUTOFF_BUFFER_MS)
        )
        logger.info(
            f"[CausalFeatureBuilder] latency_p95={self._latency_ms:.1f}ms, "
            f"cutoff_buffer={self.cutoff_buffer.total_seconds()*1000:.0f}ms"
        )

    # ── Latency measurement ─────────────────────────────────────────────────

    def _measure_system_latency(self) -> float:
        """Measure p95 execution latency (ms) from the last 100 real trades.

        Filters out extreme outliers (>30s) which indicate the signal was never
        immediately acted upon (e.g., queued signals, manual intervention).
        """
        try:
            with self._db_factory() as db:
                sql = text("""
                    SELECT
                        PERCENTILE_CONT(0.95) WITHIN GROUP (
                            ORDER BY latency_ms
                        ) AS p95_latency_ms
                    FROM (
                        SELECT
                            LEAST(
                                EXTRACT(EPOCH FROM (p.opened_at - s.signal_time)) * 1000,
                                30000.0
                            ) AS latency_ms
                        FROM positions p
                        JOIN ai_signals s
                            ON s.id = (p.extra_config->>'ai_signal_id')::uuid
                        WHERE p.source = 'ai_bot'
                          AND p.opened_at > NOW() - INTERVAL '7 days'
                          AND p.opened_at IS NOT NULL
                          AND s.signal_time IS NOT NULL
                          AND p.opened_at >= s.signal_time
                          -- Exclude extreme outliers: signals acted upon >30s later
                          -- are not "latency" but "never activated"
                          AND p.opened_at <= s.signal_time + INTERVAL '30 seconds'
                        LIMIT 1000
                    ) sq
                """)
                row = db.execute(sql).mappings().first()
                p95 = float(row["p95_latency_ms"]) if row and row["p95_latency_ms"] else None
                if p95 and p95 > 0:
                    logger.info(f"[CausalFeatureBuilder] Measured p95 latency: {p95:.1f}ms (capped at 30s)")
                    return p95
        except Exception as exc:
            logger.warning(f"[CausalFeatureBuilder] Latency measurement failed: {exc}")
        logger.info(f"[CausalFeatureBuilder] Using default latency: {_DEFAULT_LATENCY_MS}ms")
        return _DEFAULT_LATENCY_MS

    # ── Public API ──────────────────────────────────────────────────────────

    def build(self, symbol: str, signal_time: datetime) -> CausalFeatures:
        """Build causal features for a signal.

        The cutoff is: signal_time - (latency*2) - 1s safety margin.
        For recent trades we add an extra 5-minute buffer since they may still be open.
        """
        cutoff = signal_time - self.cutoff_buffer - timedelta(seconds=_SAFETY_MARGIN_S)

        tp_rate = self._tp_rate(symbol, cutoff, days=30)
        slippage = self._avg_slippage(symbol, cutoff, days=30)
        gap_freq = self._gap_frequency(symbol, cutoff, days=90)
        fee = self._fee_rate(symbol, cutoff)

        return CausalFeatures(
            tp_fill_rate_30d=tp_rate,
            avg_slippage_30d=slippage,
            gap_frequency_90d=gap_freq,
            fee_rate=fee,
        )

    # ── Internal feature builders ───────────────────────────────────────────

    def _tp_rate(self, symbol: str, cutoff: datetime, days: int) -> float | None:
        """TP fill rate over the last N days before cutoff."""
        start = cutoff - timedelta(days=days)
        # Extra buffer for trades that might still be open
        safe_cutoff = cutoff - timedelta(minutes=_RECENT_TRADE_BUFFER_MIN)

        try:
            with self._db_factory() as db:
                sql = text("""
                    SELECT
                        COUNT(*) FILTER (
                            WHERE p.realized_pnl > 0
                              AND p.closed_at IS NOT NULL
                              AND p.closed_at < :safe_cutoff
                        ) AS hits,
                        COUNT(*) FILTER (
                            WHERE p.closed_at IS NOT NULL
                              AND p.closed_at < :safe_cutoff
                        ) AS total
                    FROM positions p
                    JOIN ai_signals s
                        ON s.id = (p.extra_config->>'ai_signal_id')::uuid
                    WHERE s.ticker = :symbol
                      AND p.source = 'ai_bot'
                      AND p.opened_at BETWEEN :start AND :cutoff
                """)
                row = db.execute(sql, {
                    "symbol": symbol,
                    "start": start,
                    "cutoff": cutoff,
                    "safe_cutoff": safe_cutoff,
                }).mappings().first()

                total = int(row["total"] or 0)
                if total < _MIN_SAMPLES_FOR_FEATURE:
                    logger.debug(
                        f"[CausalFeatureBuilder] {symbol} tp_rate: insufficient data "
                        f"({total}/{_MIN_SAMPLES_FOR_FEATURE})"
                    )
                    return None

                hits = int(row["hits"] or 0)
                return round(hits / total, 4)
        except Exception as exc:
            logger.warning(f"[CausalFeatureBuilder] tp_rate failed for {symbol}: {exc}")
            return None

    def _avg_slippage(self, symbol: str, cutoff: datetime, days: int) -> float | None:
        """Average entry slippage over the last N days before cutoff."""
        start = cutoff - timedelta(days=days)
        safe_cutoff = cutoff - timedelta(minutes=_RECENT_TRADE_BUFFER_MIN)

        try:
            with self._db_factory() as db:
                sql = text("""
                    SELECT
                        AVG(
                            CASE
                                WHEN s.direction = 'long' THEN
                                    (p.entry_price - s.entry_price) / s.entry_price * 100
                                ELSE
                                    (s.entry_price - p.entry_price) / s.entry_price * 100
                            END
                        ) AS avg_slippage,
                        COUNT(*) AS total
                    FROM positions p
                    JOIN ai_signals s
                        ON s.id = (p.extra_config->>'ai_signal_id')::uuid
                    WHERE s.ticker = :symbol
                      AND p.source = 'ai_bot'
                      AND p.opened_at BETWEEN :start AND :cutoff
                      AND p.opened_at < :safe_cutoff
                      AND s.entry_price > 0
                      AND p.entry_price > 0
                """)
                row = db.execute(sql, {
                    "symbol": symbol,
                    "start": start,
                    "cutoff": cutoff,
                    "safe_cutoff": safe_cutoff,
                }).mappings().first()

                total = int(row["total"] or 0)
                if total < _MIN_SAMPLES_FOR_FEATURE:
                    logger.debug(
                        f"[CausalFeatureBuilder] {symbol} slippage: insufficient data "
                        f"({total}/{_MIN_SAMPLES_FOR_FEATURE})"
                    )
                    return None

                return round(float(row["avg_slippage"] or 0), 4)
        except Exception as exc:
            logger.warning(f"[CausalFeatureBuilder] avg_slippage failed for {symbol}: {exc}")
            return None

    def _gap_frequency(self, symbol: str, cutoff: datetime, days: int) -> float | None:
        """Frequency of SL gapping (actual loss > 1.2x theoretical loss)."""
        start = cutoff - timedelta(days=days)
        safe_cutoff = cutoff - timedelta(minutes=_RECENT_TRADE_BUFFER_MIN)

        try:
            with self._db_factory() as db:
                sql = text("""
                    SELECT
                        COUNT(*) FILTER (
                            WHERE p.realized_pnl < 0
                              AND ABS(p.realized_pnl) / NULLIF(p.entry_price * p.quantity, 0) * 100
                                  > (ABS(s.entry_price - s.stop_loss) / s.entry_price * 100) * 1.2
                        ) AS gaps,
                        COUNT(*) FILTER (WHERE p.realized_pnl < 0) AS total_losses
                    FROM positions p
                    JOIN ai_signals s
                        ON s.id = (p.extra_config->>'ai_signal_id')::uuid
                    WHERE s.ticker = :symbol
                      AND p.source = 'ai_bot'
                      AND p.opened_at BETWEEN :start AND :cutoff
                      AND p.closed_at IS NOT NULL
                      AND p.closed_at < :safe_cutoff
                      AND s.entry_price > 0
                      AND s.stop_loss > 0
                """)
                row = db.execute(sql, {
                    "symbol": symbol,
                    "start": start,
                    "cutoff": cutoff,
                    "safe_cutoff": safe_cutoff,
                }).mappings().first()

                total_losses = int(row["total_losses"] or 0)
                if total_losses < _MIN_SAMPLES_FOR_FEATURE:
                    logger.debug(
                        f"[CausalFeatureBuilder] {symbol} gap_freq: insufficient data "
                        f"({total_losses}/{_MIN_SAMPLES_FOR_FEATURE})"
                    )
                    return None

                gaps = int(row["gaps"] or 0)
                return round(gaps / total_losses, 4)
        except Exception as exc:
            logger.warning(f"[CausalFeatureBuilder] gap_frequency failed for {symbol}: {exc}")
            return None

    def _fee_rate(self, symbol: str, cutoff: datetime) -> float | None:
        """Average fee rate (total fee / notional) from recent trades before cutoff."""
        start = cutoff - timedelta(days=_LOOKBACK_DAYS)
        safe_cutoff = cutoff - timedelta(minutes=_RECENT_TRADE_BUFFER_MIN)

        try:
            with self._db_factory() as db:
                sql = text("""
                    SELECT
                        COALESCE(SUM(et.fee), 0) AS total_fee,
                        COALESCE(SUM(p.entry_price * p.quantity), 0) AS total_notional
                    FROM exchange_trades et
                    JOIN positions p ON p.id = et.position_id
                    JOIN ai_signals s ON s.id = (p.extra_config->>'ai_signal_id')::uuid
                    WHERE s.ticker = :symbol
                      AND p.source = 'ai_bot'
                      AND p.opened_at BETWEEN :start AND :cutoff
                      AND p.opened_at < :safe_cutoff
                      AND p.entry_price > 0
                      AND p.quantity > 0
                """)
                row = db.execute(sql, {
                    "symbol": symbol,
                    "start": start,
                    "cutoff": cutoff,
                    "safe_cutoff": safe_cutoff,
                }).mappings().first()

                total_fee = float(row["total_fee"] or 0)
                total_notional = float(row["total_notional"] or 0)

                if total_notional <= 0:
                    logger.debug(
                        f"[CausalFeatureBuilder] {symbol} fee_rate: no notional data"
                    )
                    return None

                return round(total_fee / total_notional, 5)
        except Exception as exc:
            logger.warning(f"[CausalFeatureBuilder] fee_rate failed for {symbol}: {exc}")
            return None
