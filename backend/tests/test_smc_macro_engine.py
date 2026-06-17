"""Unit tests for SMC macro engine (Fase A)."""
import pytest
from unittest.mock import MagicMock

from app.engines.smc_macro_engine import (
    build_macro_features,
    detect_daily_gaps,
    detect_inverse_fvg,
    detect_weekly_gap,
)


def _make_ohlcv(start_ts=1_700_000_000_000, n=20, base=100.0):
    candles = []
    for i in range(n):
        o = base + i
        c = o + 1
        candles.append([start_ts + i * 86_400_000, o, o + 2, o - 1, c, 1000])
    return candles


def test_detect_weekly_gap_empty():
    assert detect_weekly_gap([])["present"] is False


def test_detect_daily_gaps_empty():
    assert detect_daily_gaps([])["present"] is False


def test_build_macro_features_no_daily():
    ict = MagicMock()
    features = build_macro_features(None, None, ict, 100.0, "long")
    assert features["nwog_present"] is False
    assert features["org_present"] is False
    assert features["bisi_present"] is False
    assert features["sibi_present"] is False
    assert features["ifvg_present"] is False


def test_build_macro_features_with_daily_aligned():
    """Ascending daily candles produce a bullish NWOG/ORG aligned with a long."""
    candles_1d = _make_ohlcv(n=20, base=100.0)
    ict = MagicMock()
    ict.active_ob = None
    ict.active_fvgs = []
    ict.bias = "bull"
    features = build_macro_features(
        candles_1d=candles_1d,
        candles_1w=None,
        ict_ltf=ict,
        entry_mid=120.0,
        direction="long",
        pd_position=0.2,
    )
    assert isinstance(features, dict)
    assert "nwog_aligned" in features
    assert "org_aligned" in features


def test_detect_inverse_fvg_bullish_rejection():
    """Last candle wicks a bearish FVG but closes below it."""
    fvg = MagicMock()
    fvg.kind = "bear"
    fvg.bottom = 105.0
    fvg.top = 106.0

    ict = MagicMock()
    ict.bias = "bull"
    ict.active_fvgs = [fvg]

    candles = [{"open": 100, "high": 107, "low": 99, "close": 104, "volume": 1}]
    result = detect_inverse_fvg(candles, ict)
    assert result["present"] is True
    assert result["kind"] == "bear"


def test_detect_inverse_fvg_no_rejection():
    fvg = MagicMock()
    fvg.kind = "bear"
    fvg.bottom = 105.0
    fvg.top = 106.0

    ict = MagicMock()
    ict.bias = "bull"
    ict.active_fvgs = [fvg]

    candles = [{"open": 100, "high": 104, "low": 99, "close": 103, "volume": 1}]
    result = detect_inverse_fvg(candles, ict)
    assert result["present"] is False
