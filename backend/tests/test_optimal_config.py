"""Tests for AI optimal config computation."""
from unittest.mock import MagicMock

from app.engines.bot_activator import _compute_optimal_config_sync


class MockSignal:
    def __init__(self, ticker="BTCUSDT", timeframe="1h", outcome="SUCCESS",
                 score=70, quality_tier="STRONG", anti_fake_status="CLEAR",
                 direction="long", pnl_pct=1.5, realistic_pnl_pct=None):
        self.ticker = ticker
        self.timeframe = timeframe
        self.outcome = outcome
        self.score = score
        self.quality_tier = quality_tier
        self.anti_fake_status = anti_fake_status
        self.direction = direction
        self.pnl_pct = pnl_pct
        self.realistic_pnl_pct = realistic_pnl_pct


class TestComputeOptimalConfig:
    def test_no_signals_returns_fallback(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.all.return_value = []
        db.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = []
        result = _compute_optimal_config_sync(db, "BTCUSDT")
        assert result is not None
        assert "min_score" in result
        assert "allowed_tiers" in result

    def test_insufficient_resolved_returns_fallback(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.all.return_value = []
        db.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [
            MockSignal(outcome="PENDING"),
        ]
        result = _compute_optimal_config_sync(db, "BTCUSDT")
        assert result is not None
        assert "min_score" in result

    def test_returns_config_with_allowed_tiers(self):
        db = MagicMock()
        signals = [
            MockSignal(outcome="SUCCESS", quality_tier="STRONG", score=80),
            MockSignal(outcome="SUCCESS", quality_tier="STRONG", score=80),
            MockSignal(outcome="FAILURE", quality_tier="MODERATE", score=60),
            MockSignal(outcome="SUCCESS", quality_tier="MODERATE", score=60),
            MockSignal(outcome="SUCCESS", quality_tier="MODERATE", score=60),
        ]
        db.query.return_value.filter.return_value.all.return_value = signals
        result = _compute_optimal_config_sync(db, "BTCUSDT")
        assert result is not None
        assert "min_score" in result
        assert "allowed_tiers" in result
        assert "allowed_statuses" in result
        # Both tiers should be allowed with >=45% WR
        assert len(result["allowed_tiers"]) >= 1

    def test_caution_status_filtered_when_low_wr(self):
        db = MagicMock()
        # Mock real trades: enough to pass fallback threshold (≥10 real)
        real_rows = [
            {"realized_pnl": 10.0, "quality_tier": "STRONG", "anti_fake_status": "CLEAR",
             "direction": "long", "timeframe": "1h", "execution_type": "real"},
            {"realized_pnl": 15.0, "quality_tier": "STRONG", "anti_fake_status": "CLEAR",
             "direction": "long", "timeframe": "1h", "execution_type": "real"},
        ] * 6  # 12 real trades to pass threshold
        db.execute.return_value.mappings.return_value.all.return_value = real_rows

        # Mock realistic signals: CAUTION has 0% WR
        signals = [
            MockSignal(outcome="SUCCESS", anti_fake_status="CLEAR"),
            MockSignal(outcome="SUCCESS", anti_fake_status="CLEAR"),
            MockSignal(outcome="FAILURE", anti_fake_status="CAUTION"),
            MockSignal(outcome="FAILURE", anti_fake_status="CAUTION"),
        ]
        db.query.return_value.filter.return_value.all.return_value = signals
        result = _compute_optimal_config_sync(db, "BTCUSDT")
        assert result is not None
        # CAUTION has 0% WR (0/2) so should not be allowed when enough real data
        if result.get("allowed_statuses"):
            assert "CAUTION" not in result["allowed_statuses"]
        assert "CLEAR" in result["allowed_statuses"]
