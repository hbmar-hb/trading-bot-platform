"""Unit tests for the live-vs-shadow deployment mode."""
from __future__ import annotations

import json

import pytest

from ai.services.shadow_mode import ShadowDeployer, record_shadow


@pytest.fixture
def deployer(fake_redis):
    return ShadowDeployer()


def test_record_shadow_stores_prediction(fake_redis):
    record_shadow("sig-001", live_prob=0.6, shadow_prob=0.7)
    items = fake_redis.lrange("shadow_mode:predictions", 0, -1)
    assert len(items) == 1
    pred = json.loads(items[0])
    assert pred["signal_id"] == "sig-001"
    assert pred["live_prob"] == 0.6
    assert pred["shadow_prob"] == 0.7


def test_resolve_updates_shadow_prediction(deployer, fake_redis):
    deployer.record("sig-001", live_prob=0.6, shadow_prob=0.7)
    deployer.resolve("sig-001", "WIN", 0.012)

    items = fake_redis.lrange("shadow_mode:predictions", 0, -1)
    pred = json.loads(items[0])
    assert pred["actual_outcome"] == "WIN"
    assert pred["pnl_pct"] == 0.012


def test_evaluate_promotion_shadow_wins(deployer):
    for i in range(105):
        sid = f"sig-{i:03d}"
        deployer.record(sid, live_prob=0.4, shadow_prob=0.6)
        deployer.resolve(sid, "WIN", 0.01)

    result = deployer.evaluate_promotion()
    assert result["promote"] is True
    assert result["shadow_sharpe"] > result["live_sharpe"] * 1.2


def test_evaluate_promotion_live_wins(deployer):
    for i in range(105):
        sid = f"sig-{i:03d}"
        deployer.record(sid, live_prob=0.6, shadow_prob=0.4)
        deployer.resolve(sid, "WIN", 0.01)

    result = deployer.evaluate_promotion()
    assert result["promote"] is False


def test_evaluate_promotion_insufficient_signals(deployer):
    result = deployer.evaluate_promotion()
    assert result["promote"] is False
    assert "insufficient_signals" in result["reason"]
