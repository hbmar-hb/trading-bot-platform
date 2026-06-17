"""Test suite for anti-look-ahead verification in realistic outcome engine.

These tests MUST pass before any deployment. If look-ahead is detected,
the build should fail.
"""
import pytest
from datetime import datetime, timezone

from app.engines.realistic_outcome_engine import simulate_outcome, _verify_no_look_ahead
from app.services.execution_analytics import DEFAULT_PROFILE


class FakeSignal:
    def __init__(self, signal_time, timeframe="1h"):
        self.id = "test-signal-001"
        self.ticker = "BTCUSDT"
        self.timeframe = timeframe
        self.direction = "long"
        self.entry_price = 100000.0
        self.stop_loss = 99000.0
        self.take_profit_1 = 101500.0
        self.take_profit_2 = 102500.0
        self.signal_time = signal_time


def test_look_ahead_detected_when_candle_before_signal():
    """A candle with timestamp BEFORE signal_time is look-ahead. Must raise."""
    sig_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig = FakeSignal(sig_time)

    # Candle timestamp BEFORE signal time
    bad_candles = [
        [int(sig_time.timestamp() * 1000) - 3600000, 100000, 101000, 99000, 100500],  # 1h before
    ]

    with pytest.raises(ValueError, match="Look-ahead detected"):
        simulate_outcome(sig, bad_candles, profile=DEFAULT_PROFILE)


def test_valid_candles_after_signal_pass():
    """Candles strictly after signal_time should pass without error."""
    sig_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig = FakeSignal(sig_time)

    valid_candles = [
        [int(sig_time.timestamp() * 1000) + 3600000, 100000, 101600, 99900, 101000],
    ]

    result = simulate_outcome(sig, valid_candles, profile=DEFAULT_PROFILE)
    assert result.outcome in ("SUCCESS", "FAILURE_MAX_ADVERSE", "FAILURE_BEHAVIORAL", "EXPIRED")


def test_verify_function_standalone():
    """Test the _verify_no_look_ahead function directly."""
    sig_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    sig = FakeSignal(sig_time)

    # Valid
    _verify_no_look_ahead(sig, [
        [int(sig_time.timestamp() * 1000) + 3600000, 100000, 101000, 99000, 100500],
    ])

    # Invalid
    with pytest.raises(ValueError, match="Look-ahead detected"):
        _verify_no_look_ahead(sig, [
            [int(sig_time.timestamp() * 1000) - 1000, 100000, 101000, 99000, 100500],
        ])
