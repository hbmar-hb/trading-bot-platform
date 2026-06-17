"""Unit tests for the candidate shadow mode (Fase D)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from ai.services.candidate_shadow_mode import (
    CandidatePrediction,
    CandidateShadowDeployer,
    record_candidate_shadow,
    resolve_candidate_shadow,
)


@pytest.fixture
def deployer(fake_redis):
    return CandidateShadowDeployer()


def _make_resolved_predictions(deployer, n: int = 35):
    """Seed the deployer with n resolved predictions where candidate wins."""
    for i in range(n):
        sid = f"sig-{i:03d}"
        deployer.record(sid, live_prob=0.4, candidate_prob=0.6)
        # Vary PnL so Sharpe is well-defined and positive.
        pnl = 0.02 if i % 2 == 0 else 0.01
        deployer.resolve(sid, "WIN", pnl)


def test_record_stores_json_prediction(deployer, fake_redis):
    deployer.record("abc-123", live_prob=0.55, candidate_prob=0.65)

    items = fake_redis.lrange("shadow_mode:candidate_predictions", 0, -1)
    assert len(items) == 1

    pred = json.loads(items[0])
    assert pred["signal_id"] == "abc-123"
    assert pred["live_prob"] == 0.55
    assert pred["candidate_prob"] == 0.65
    assert pred["actual_outcome"] is None
    assert pred["pnl_pct"] is None
    assert "timestamp" in pred


def test_record_rejects_none_signal_id(deployer, fake_redis):
    deployer.record("None", live_prob=0.55, candidate_prob=0.65)
    assert fake_redis.llen("shadow_mode:candidate_predictions") == 0


def test_resolve_updates_outcome_and_pnl(deployer, fake_redis):
    deployer.record("abc-123", live_prob=0.55, candidate_prob=0.65)
    deployer.resolve("abc-123", "WIN", 1.23)

    items = fake_redis.lrange("shadow_mode:candidate_predictions", 0, -1)
    pred = json.loads(items[0])
    assert pred["actual_outcome"] == "WIN"
    assert pred["pnl_pct"] == 1.23


def test_resolve_does_not_mutate_other_signals(deployer, fake_redis):
    deployer.record("abc-123", live_prob=0.55, candidate_prob=0.65)
    deployer.record("def-456", live_prob=0.55, candidate_prob=0.65)
    deployer.resolve("abc-123", "WIN", 1.23)

    items = fake_redis.lrange("shadow_mode:candidate_predictions", 0, -1)
    preds = [json.loads(i) for i in items]
    abc = next(p for p in preds if p["signal_id"] == "abc-123")
    dff = next(p for p in preds if p["signal_id"] == "def-456")
    assert abc["actual_outcome"] == "WIN"
    assert dff["actual_outcome"] is None


def test_evaluate_promotion_insufficient_signals(deployer):
    result = deployer.evaluate_promotion()
    assert result["promote"] is False
    assert "insufficient_signals" in result["reason"]
    assert result["n_signals"] == 0


def test_evaluate_promotion_candidate_outperforms_live(deployer):
    _make_resolved_predictions(deployer, n=35)
    result = deployer.evaluate_promotion()
    assert result["promote"] is True
    assert result["candidate_sharpe"] > result["live_sharpe"] * 1.2


def test_evaluate_promotion_live_outperforms_candidate(deployer):
    now = datetime.now(timezone.utc)
    for i in range(35):
        sid = f"sig-{i:03d}"
        deployer.record(sid, live_prob=0.6, candidate_prob=0.4)
        deployer.resolve(sid, "WIN", 0.01)

    result = deployer.evaluate_promotion()
    assert result["promote"] is False
    assert result["reason"] == "candidate_does_not_outperform_live"


def test_evaluate_promotion_ignores_predictions_outside_window(deployer, fake_redis):
    old_pred = CandidatePrediction(
        signal_id="old-001",
        timestamp=(datetime.now(timezone.utc) - timedelta(hours=50)).isoformat(),
        live_prob=0.6,
        candidate_prob=0.6,
        actual_outcome="WIN",
        pnl_pct=0.05,
    )
    fake_redis.rpush("shadow_mode:candidate_predictions", json.dumps(old_pred.__dict__))

    result = deployer.evaluate_promotion()
    assert result["n_signals"] == 0


def test_record_candidate_shadow_convenience_function(fake_redis):
    record_candidate_shadow("conv-001", live_prob=0.5, candidate_prob=0.7)
    items = fake_redis.lrange("shadow_mode:candidate_predictions", 0, -1)
    assert len(items) == 1
    assert json.loads(items[0])["signal_id"] == "conv-001"


def test_resolve_candidate_shadow_convenience_function(fake_redis):
    record_candidate_shadow("conv-002", live_prob=0.5, candidate_prob=0.7)
    resolve_candidate_shadow("conv-002", "LOSS", -0.02)
    items = fake_redis.lrange("shadow_mode:candidate_predictions", 0, -1)
    assert json.loads(items[0])["actual_outcome"] == "LOSS"
