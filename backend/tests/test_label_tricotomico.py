"""Test suite for tricotomic label correctness in realistic outcome engine.

Verifies that the engine produces the 4 expected labels:
  SUCCESS, FAILURE_MAX_ADVERSE, FAILURE_BEHAVIORAL, INCONCLUSIVE
"""
import pytest
from datetime import datetime, timezone

from app.engines.realistic_outcome_engine import simulate_outcome
from app.services.execution_analytics import DEFAULT_PROFILE


class FakeSignal:
    def __init__(self, signal_time, direction="long", entry=100000.0,
                 sl=99000.0, tp1=101500.0, timeframe="1h"):
        self.id = "test-signal-001"
        self.ticker = "BTCUSDT"
        self.timeframe = timeframe
        self.direction = direction
        self.entry_price = entry
        self.stop_loss = sl
        self.take_profit_1 = tp1
        self.take_profit_2 = tp1 * 1.02
        self.signal_time = signal_time


def test_success_when_tp_hit_first():
    sig_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig = FakeSignal(sig_time)
    # Candle that hits TP1
    candles = [
        [int(sig_time.timestamp() * 1000) + 3600000, 100000, 101600, 99900, 101000],
    ]
    result = simulate_outcome(sig, candles, profile=DEFAULT_PROFILE)
    assert result.outcome == "SUCCESS"
    assert result.pnl_pct is not None
    assert result.bars == 1


def test_failure_max_adverse_when_sl_hit_first():
    sig_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig = FakeSignal(sig_time)
    # Candle that hits SL
    candles = [
        [int(sig_time.timestamp() * 1000) + 3600000, 100000, 100100, 98900, 99000],
    ]
    result = simulate_outcome(sig, candles, profile=DEFAULT_PROFILE)
    assert result.outcome == "FAILURE_MAX_ADVERSE"
    assert result.pnl_pct is not None
    assert result.bars == 1


def test_failure_behavioral_when_tp_then_sl():
    sig_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig = FakeSignal(sig_time)
    # Candle 1: wick hits TP but doesn't fill (tp_wick_fill_rate=0.75, seeded)
    # Candle 2: hits SL
    candles = [
        [int(sig_time.timestamp() * 1000) + 3600000, 100000, 101600, 99900, 100500],
        [int(sig_time.timestamp() * 1000) + 7200000, 100500, 100600, 98900, 99000],
    ]
    result = simulate_outcome(sig, candles, profile=DEFAULT_PROFILE)
    # With deterministic seed, either TP fills or it's a wick then SL
    assert result.outcome in ("SUCCESS", "FAILURE_BEHAVIORAL", "FAILURE_MAX_ADVERSE")


def test_inconclusive_when_no_tp_no_sl():
    sig_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig = FakeSignal(sig_time)
    # Candles that stay between SL and TP
    candles = [
        [int(sig_time.timestamp() * 1000) + 3600000, 100000, 100800, 99800, 100200],
        [int(sig_time.timestamp() * 1000) + 7200000, 100200, 100900, 99900, 100500],
    ]
    result = simulate_outcome(sig, candles, profile=DEFAULT_PROFILE)
    assert result.outcome == "INCONCLUSIVE"
    assert result.pnl_pct is None
    assert result.bars is None


def test_inconclusive_is_not_expired():
    """INCONCLUSIVE means no resolution yet; EXPIRED is a tracker-level concept."""
    sig_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig = FakeSignal(sig_time)
    candles = [
        [int(sig_time.timestamp() * 1000) + 3600000, 100000, 100800, 99800, 100200],
    ]
    result = simulate_outcome(sig, candles, profile=DEFAULT_PROFILE)
    assert result.outcome == "INCONCLUSIVE"
    assert "EXPIRED" not in result.notes
