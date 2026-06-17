"""Tests for app/engines/dynamic_risk_builder."""
from __future__ import annotations

import pytest

from app.core.ict_engine import ICTResult, OrderBlock, FVG, ForwardLevel
from app.engines.dynamic_risk_builder import build_levels


def _make_ict(
    direction: str,
    active_ob: OrderBlock | None = None,
    active_fvgs: list | None = None,
    eq_highs: list | None = None,
    eq_lows: list | None = None,
    forward_levels: list | None = None,
    support_levels: list | None = None,
) -> ICTResult:
    return ICTResult(
        bias="bull" if direction == "long" else "bear",
        last_break=None,
        active_ob=active_ob,
        active_fvgs=active_fvgs or [],
        eq_highs=eq_highs or [],
        eq_lows=eq_lows or [],
        signal=direction,
        entry_zone=(95.0, 96.0),
        trigger="ob",
        forward_levels=forward_levels or [],
        support_levels=support_levels or [],
    )


def test_long_sl_at_ob_bottom_with_buffer():
    ob = OrderBlock(bar=10, top=94.0, bottom=93.0, kind="bull")
    ict = _make_ict("long", active_ob=ob)
    plan = build_levels(entry_mid=95.5, direction="long", score=80, quality_tier="STRONG", ict=ict, atr_value=1.0)

    # SL should be below OB bottom, with a small buffer for high score
    assert plan.stop_loss < 93.0
    assert plan.stop_loss > 90.0
    assert "ob" in plan.sl_basis.lower() or "active_ob" in plan.sl_basis.lower()


def test_tp1_respects_minimum_r():
    ob = OrderBlock(bar=10, top=94.0, bottom=93.0, kind="bull")
    forward = [
        ForwardLevel(price=96.0, kind="fvg_bear", distance_pct=1.0, liquidity_type="IRL"),
    ]
    ict = _make_ict("long", active_ob=ob, forward_levels=forward)
    plan = build_levels(entry_mid=95.5, direction="long", score=80, quality_tier="STRONG", ict=ict, atr_value=1.0)

    risk = abs(95.5 - plan.stop_loss)
    tp1_r = abs(plan.take_profit_1 - 95.5) / risk
    assert tp1_r >= 1.2, f"TP1 R={tp1_r:.2f} below minimum 1.2"


def test_short_sl_at_ob_top_with_buffer():
    ob = OrderBlock(bar=10, top=97.0, bottom=96.0, kind="bear")
    ict = _make_ict("short", active_ob=ob)
    plan = build_levels(entry_mid=95.5, direction="short", score=80, quality_tier="STRONG", ict=ict, atr_value=1.0)

    assert plan.stop_loss > 97.0
    assert "ob" in plan.sl_basis.lower() or "active_ob" in plan.sl_basis.lower()


def test_tp_levels_have_adaptive_splits():
    ob = OrderBlock(bar=10, top=94.0, bottom=93.0, kind="bull")
    forward = [
        ForwardLevel(price=99.0, kind="eq_high", distance_pct=3.5, liquidity_type="ERL"),
        ForwardLevel(price=102.0, kind="eq_high", distance_pct=6.5, liquidity_type="ERL"),
    ]
    ict = _make_ict("long", active_ob=ob, forward_levels=forward)

    # High score → let more run
    plan_high = build_levels(entry_mid=95.5, direction="long", score=80, quality_tier="STRONG", ict=ict, atr_value=1.0)
    assert plan_high.tp_levels[0].close_percent == pytest.approx(0.35, abs=0.01)

    # Low score → take more at TP1
    plan_low = build_levels(entry_mid=95.5, direction="long", score=50, quality_tier="WEAK", ict=ict, atr_value=1.0)
    assert plan_low.tp_levels[0].close_percent == pytest.approx(0.65, abs=0.01)


def test_sl_clamped_to_max_pct():
    ob = OrderBlock(bar=10, top=50.0, bottom=40.0, kind="bull")
    ict = _make_ict("long", active_ob=ob)
    plan = build_levels(
        entry_mid=95.5, direction="long", score=80, quality_tier="STRONG",
        ict=ict, atr_value=1.0, max_sl_pct=0.02,
    )
    risk_pct = abs(95.5 - plan.stop_loss) / 95.5
    assert risk_pct <= 0.0201
