"""Integration tests for the shadow-mode flow against a real Redis instance.

These are skipped automatically if Redis is not reachable.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.services.ai_scanner import record_shadow_for_signal
from app.services.cache import sync_redis


@pytest.fixture(scope="module")
def redis_available():
    try:
        sync_redis.ping()
        return True
    except Exception:
        return False


@pytest.fixture
def clean_shadow_keys(redis_available):
    if not redis_available:
        pytest.skip("Redis not available")
    keys = ["shadow_mode:predictions", "shadow_mode:candidate_predictions"]
    backup = {k: sync_redis.lrange(k, 0, -1) for k in keys}
    for k in keys:
        sync_redis.delete(k)
    yield
    for k in keys:
        sync_redis.delete(k)
        if backup[k]:
            sync_redis.rpush(k, *backup[k])


@pytest.mark.integration
def test_record_shadow_for_signal_writes_real_uuid(clean_shadow_keys):
    signal_id = str(uuid.uuid4())
    result_dict = {
        "symbol": "BTCUSDT",
        "status": "SIGNAL",
        "context": {},
        "_shadow_probs": {
            "live": 0.75,
            "shadow": 0.60,
            "candidate": 0.80,
        },
    }

    record_shadow_for_signal(signal_id, result_dict)

    live_items = sync_redis.lrange("shadow_mode:predictions", 0, -1)
    cand_items = sync_redis.lrange("shadow_mode:candidate_predictions", 0, -1)

    assert len(live_items) == 1
    assert len(cand_items) == 1

    live_pred = json.loads(live_items[0])
    cand_pred = json.loads(cand_items[0])

    assert live_pred["signal_id"] == signal_id
    assert live_pred["signal_id"] != "None"
    assert live_pred["live_prob"] == 0.75
    assert live_pred["shadow_prob"] == 0.60

    assert cand_pred["signal_id"] == signal_id
    assert cand_pred["candidate_prob"] == 0.80


@pytest.mark.integration
def test_no_none_signal_ids_after_fix(clean_shadow_keys):
    """Guard against the regression where signal_id was stored as the string 'None'."""
    signal_id = str(uuid.uuid4())
    record_shadow_for_signal(
        signal_id,
        {
            "_shadow_probs": {"live": 0.5, "shadow": 0.5, "candidate": 0.5},
        },
    )

    for key in ["shadow_mode:predictions", "shadow_mode:candidate_predictions"]:
        items = sync_redis.lrange(key, 0, -1)
        for item in items:
            pred = json.loads(item)
            assert pred["signal_id"] != "None"
            assert len(pred["signal_id"]) == 36  # UUID length
