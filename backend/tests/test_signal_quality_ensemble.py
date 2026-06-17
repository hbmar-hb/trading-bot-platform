"""Tests for RSI/Stochastic + Volume Profile ensemble in signal quality engine."""
from dataclasses import field

from app.engines.signal_quality_engine import assess_quality
from app.engines.confluence_engine import ConfluenceResult


def make_result(direction="long", score=70.0, features=None):
    return ConfluenceResult(
        direction=direction,
        score=score,
        confidence="HIGH",
        entry_price=100.0,
        entry_zone=(99.0, 101.0),
        stop_loss=95.0,
        take_profit_1=105.0,
        take_profit_2=110.0,
        risk_reward=1.5,
        features=features or {},
    )


class TestRSIEnsemble:
    def test_rsi_oversold_long_adds_bonus(self):
        r = make_result("long", features={"rsi": 25.0, "stoch_k": 50.0})
        qa = assess_quality(r)
        assert any("RSI sobrevendido" in g for g in qa.green_flags)
        # Should have bonus compared to neutral RSI
        r2 = make_result("long", features={"rsi": 50.0, "stoch_k": 50.0})
        qa2 = assess_quality(r2)
        assert qa.quality_score > qa2.quality_score

    def test_rsi_overbought_long_adds_red_flag(self):
        r = make_result("long", features={"rsi": 75.0, "stoch_k": 50.0})
        qa = assess_quality(r)
        assert any("RSI sobrecomprado" in f for f in qa.red_flags)

    def test_rsi_overbought_short_adds_bonus(self):
        r = make_result("short", features={"rsi": 75.0, "stoch_k": 50.0})
        qa = assess_quality(r)
        assert any("RSI sobrecomprado" in g for g in qa.green_flags)


class TestStochasticEnsemble:
    def test_stoch_oversold_long_adds_bonus(self):
        r = make_result("long", features={"rsi": 50.0, "stoch_k": 15.0})
        qa = assess_quality(r)
        assert any("Stochastic sobrevendido" in g for g in qa.green_flags)

    def test_stoch_overbought_short_adds_bonus(self):
        r = make_result("short", features={"rsi": 50.0, "stoch_k": 85.0})
        qa = assess_quality(r)
        assert any("Stochastic sobrecomprado" in g for g in qa.green_flags)


class TestVolumeProfilePOC:
    def test_poc_near_entry_adds_bonus(self):
        r = make_result("long", features={"rsi": 50.0, "stoch_k": 50.0, "poc": 100.0})
        qa = assess_quality(r)
        assert any("POC" in g for g in qa.green_flags)

    def test_poc_far_entry_no_bonus(self):
        r = make_result("long", features={"rsi": 50.0, "stoch_k": 50.0, "poc": 150.0})
        qa = assess_quality(r)
        assert not any("POC" in g for g in qa.green_flags)
