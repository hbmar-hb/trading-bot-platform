"""Tests for ContextThresholdRegistry (CATR)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.context_thresholds import ContextThresholdRegistry


@pytest.fixture
def mock_redis():
    """Mock Redis client with in-memory storage."""
    store = {}

    class FakeRedis:
        def get(self, key):
            return store.get(key)

        def setex(self, key, ttl, value):
            store[key] = value

        def delete(self, key):
            store.pop(key, None)

        def pipeline(self):
            pipe = MagicMock()

            def _get(k):
                return store.get(k)

            def _setex(k, ttl, v):
                store[k] = v

            pipe.get = _get
            pipe.setex = _setex
            pipe.execute = lambda: []
            return pipe

    return FakeRedis(), store


class TestContextThresholdRegistry:
    def test_get_fallback_when_no_data(self, mock_redis):
        fake_redis, _ = mock_redis
        with patch("app.services.context_thresholds.sync_redis", fake_redis):
            catr = ContextThresholdRegistry()
            result = catr.get("BTCUSDT", "1h", "trending")

        assert result["reason"] == "no_data"
        assert result["confidence"] == 0.0
        assert result["score_threshold"] == 75

    def test_get_fallback_when_insufficient_samples(self, mock_redis):
        fake_redis, store = mock_redis
        store["catr:BTCUSDT:1h:trending"] = json.dumps({
            "n_trades": 5,
            "winrate_window": [1, 0, 1, 1, 0],
        })

        with patch("app.services.context_thresholds.sync_redis", fake_redis):
            catr = ContextThresholdRegistry()
            result = catr.get("BTCUSDT", "1h", "trending")

        assert result["reason"] == "insufficient_data"
        assert result["partial_n_trades"] == 5

    def test_get_optimized_when_enough_samples(self, mock_redis):
        fake_redis, store = mock_redis
        # 20 trades, 70% winrate, PF ~2.0
        store["catr:BTCUSDT:1h:trending"] = json.dumps({
            "n_trades": 20,
            "score_threshold": 75,
            "prob_threshold": 0.70,
            "winrate_window": [1] * 14 + [0] * 6,
            "gross_profits": [2.0] * 14,
            "gross_losses": [1.0] * 6,
        })

        with patch("app.services.context_thresholds.sync_redis", fake_redis):
            catr = ContextThresholdRegistry()
            result = catr.get("BTCUSDT", "1h", "trending")

        assert result["reason"] == "context_optimized"
        assert result["confidence"] > 0.0
        assert result["recent_winrate"] == 0.70
        # Zona verde: thresholds deberían subir ligeramente
        assert result["score_threshold"] >= 75

    def test_get_red_zone_raises_thresholds(self, mock_redis):
        fake_redis, store = mock_redis
        # 20 trades, 30% winrate, PF < 0.9
        store["catr:ETHUSDT:15m:ranging"] = json.dumps({
            "n_trades": 20,
            "score_threshold": 75,
            "prob_threshold": 0.70,
            "winrate_window": [0] * 14 + [1] * 6,
            "gross_profits": [1.0] * 6,
            "gross_losses": [2.0] * 14,
        })

        with patch("app.services.context_thresholds.sync_redis", fake_redis):
            catr = ContextThresholdRegistry()
            result = catr.get("ETHUSDT", "15m", "ranging")

        # Zona roja: thresholds deberían subir significativamente
        assert result["score_threshold"] > 75
        assert result["prob_threshold"] > 0.70

    def test_update_creates_registry(self, mock_redis):
        fake_redis, store = mock_redis

        with patch("app.services.context_thresholds.sync_redis", fake_redis):
            catr = ContextThresholdRegistry()
            catr.update(
                "BTCUSDT", "1h", "trending",
                outcome={"pnl_pct": 1.5, "signal_score": 82, "label": "SUCCESS"}
            )

        key = "catr:BTCUSDT:1h:trending"
        assert key in store
        data = json.loads(store[key])
        assert data["n_trades"] == 1
        assert data["winrate_window"] == [1]
        assert data["gross_profits"] == [1.5]

    def test_update_appends_loss(self, mock_redis):
        fake_redis, store = mock_redis

        with patch("app.services.context_thresholds.sync_redis", fake_redis):
            catr = ContextThresholdRegistry()
            catr.update(
                "BTCUSDT", "1h", "trending",
                outcome={"pnl_pct": -1.0, "signal_score": 78, "label": "FAILURE"}
            )

        data = json.loads(store["catr:BTCUSDT:1h:trending"])
        assert data["winrate_window"] == [0]
        assert data["gross_losses"] == [1.0]
        assert data["gross_profits"] == []

    def test_update_window_capping(self, mock_redis):
        fake_redis, store = mock_redis
        # Pre-populate with WINDOW_SIZE entries
        store["catr:BTCUSDT:1h:trending"] = json.dumps({
            "n_trades": 50,
            "score_threshold": 75,
            "prob_threshold": 0.70,
            "winrate_window": [1] * 50,
            "gross_profits": [1.0] * 50,
            "gross_losses": [],
        })

        with patch("app.services.context_thresholds.sync_redis", fake_redis):
            catr = ContextThresholdRegistry()
            catr.update(
                "BTCUSDT", "1h", "trending",
                outcome={"pnl_pct": -2.0, "label": "FAILURE"}
            )

        data = json.loads(store["catr:BTCUSDT:1h:trending"])
        assert len(data["winrate_window"]) == 50
        assert data["winrate_window"][-1] == 0  # último es loss

    def test_compute_pf(self):
        assert ContextThresholdRegistry._compute_pf([2, 3], [1]) == 5.0
        assert ContextThresholdRegistry._compute_pf([], [1]) == 0.0
        assert ContextThresholdRegistry._compute_pf([1, 2], []) == 999.0
        assert ContextThresholdRegistry._compute_pf([], []) == 0.0
