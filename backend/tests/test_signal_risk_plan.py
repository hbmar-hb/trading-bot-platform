"""Tests for SignalRiskPlanner (SAPP)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.signal_risk_plan import SignalRiskPlanner, TPLevel, calculate_tp_prices


class FakeSignal:
    """Mock AISignal for testing."""

    def __init__(self, quality_tier="STRONG", score=82, prob=0.72, timeframe="1h"):
        self.quality_tier = quality_tier
        self.score = score
        self.success_probability = prob
        self.timeframe = timeframe


class TestSignalRiskPlanner:
    def test_strong_exceptional_plan(self):
        sig = FakeSignal(quality_tier="STRONG", score=88, prob=0.78)
        planner = SignalRiskPlanner()
        plan = planner.generate_plan(sig, account_equity=10000)

        assert plan.quality_tier == "STRONG"
        assert plan.execution_mode == "aggressive"
        assert len(plan.tp_levels) == 3
        assert plan.tp_levels[0].r_multiple == 1.5
        assert plan.tp_levels[1].r_multiple == 2.5
        assert plan.tp_levels[2].r_multiple == 4.0
        assert plan.emergency_brake_at_r == -1.5

    def test_moderate_high_score_plan(self):
        sig = FakeSignal(quality_tier="MODERATE", score=78, prob=0.65)
        planner = SignalRiskPlanner()
        plan = planner.generate_plan(sig, account_equity=10000)

        assert len(plan.tp_levels) == 2
        assert plan.tp_levels[0].close_pct == 0.60
        assert plan.execution_mode == "standard"
        assert plan.emergency_brake_at_r == -1.0

    def test_moderate_low_score_plan(self):
        sig = FakeSignal(quality_tier="MODERATE", score=75, prob=0.65)
        planner = SignalRiskPlanner()
        plan = planner.generate_plan(sig, account_equity=10000)

        assert len(plan.tp_levels) == 1
        assert plan.tp_levels[0].close_pct == 1.0
        assert plan.execution_mode == "standard"
        assert plan.emergency_brake_at_r == -1.0

    def test_weak_plan(self):
        sig = FakeSignal(quality_tier="WEAK", score=60, prob=0.55)
        planner = SignalRiskPlanner()
        plan = planner.generate_plan(sig, account_equity=10000)

        assert len(plan.tp_levels) == 1
        assert plan.tp_levels[0].close_pct == 1.0
        assert plan.emergency_brake_at_r == -0.5

    def test_time_limit_ranging(self):
        sig = FakeSignal(quality_tier="STRONG", score=70, prob=0.60)
        planner = SignalRiskPlanner()
        plan = planner.generate_plan(
            sig, account_equity=10000, market_context={"regime": "ranging"}
        )
        base = 24  # 1h base
        assert plan.time_limit_bars == int(base * 0.6)

    def test_time_limit_high_score(self):
        sig = FakeSignal(quality_tier="STRONG", score=90, prob=0.80)
        planner = SignalRiskPlanner()
        plan = planner.generate_plan(sig, account_equity=10000)
        base = 24
        assert plan.time_limit_bars == int(base * 1.4)

    def test_sl_multiplier_high_score(self):
        sig = FakeSignal(quality_tier="STRONG", score=88, prob=0.75)
        planner = SignalRiskPlanner()
        plan = planner.generate_plan(
            sig, account_equity=10000, market_context={"atr_14": 100}
        )
        # score>82 => 0.85 mult => sl_distance = 100 * 0.85 = 85
        assert plan.sl_distance == pytest.approx(85.0, rel=0.01)

    def test_sl_multiplier_low_score(self):
        sig = FakeSignal(quality_tier="MODERATE", score=60, prob=0.55)
        planner = SignalRiskPlanner()
        plan = planner.generate_plan(
            sig, account_equity=10000, market_context={"atr_14": 100}
        )
        # score<65 => 1.25 mult, prob<0.6 => 1.15 mult => 1.4375
        assert plan.sl_distance == pytest.approx(143.75, rel=0.01)

    def test_sizing_by_quality(self):
        planner = SignalRiskPlanner()

        strong = planner.generate_plan(FakeSignal("STRONG"), 10000)
        moderate = planner.generate_plan(FakeSignal("MODERATE"), 10000)
        weak = planner.generate_plan(FakeSignal("WEAK"), 10000)

        assert strong.size_usd == 200.0  # 2%
        assert moderate.size_usd == 70.0  # 1% * 0.7
        assert weak.size_usd == 20.0  # 0.5% * 0.4


class TestCalculateTPPrices:
    def test_long_tp_prices(self):
        entry = Decimal("100")
        sl = Decimal("98")
        levels = [
            TPLevel(1, 0.30, 1.5, "breakeven"),
            TPLevel(2, 0.40, 2.5, "trailing"),
        ]
        records = calculate_tp_prices(entry, "long", sl, levels)

        assert len(records) == 2
        # risk = 2, TP1 = 100 + 2*1.5 = 103
        assert records[0]["price"] == pytest.approx(103.0)
        assert records[0]["close_percent"] == 0.30
        # TP2 = 100 + 2*2.5 = 105
        assert records[1]["price"] == pytest.approx(105.0)

    def test_short_tp_prices(self):
        entry = Decimal("100")
        sl = Decimal("102")
        levels = [TPLevel(1, 0.50, 1.5, "breakeven")]
        records = calculate_tp_prices(entry, "short", sl, levels)

        assert len(records) == 1
        # risk = 2, TP1 = 100 - 2*1.5 = 97
        assert records[0]["price"] == pytest.approx(97.0)

    def test_zero_risk_distance(self):
        entry = Decimal("100")
        sl = Decimal("100")
        levels = [TPLevel(1, 1.0, 1.5, "breakeven")]
        records = calculate_tp_prices(entry, "long", sl, levels)
        assert records == []
