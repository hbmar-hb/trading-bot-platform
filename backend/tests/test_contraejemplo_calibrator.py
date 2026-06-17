"""Tests for ContraejemploCalibrator (CDFC)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from app.services.adaptive_weight_optimizer import ContraejemploCalibrator


class FakeSignal:
    def __init__(self, outcome, features, resolved_at=None):
        self.outcome = outcome
        self.features = features
        self.resolved_at = resolved_at or datetime.now(timezone.utc)


class TestContraejemploCalibrator:
    def test_no_failures_no_penalty(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        cal = ContraejemploCalibrator(db)
        deltas = cal.analyze_recent_failures(hours_back=24)
        assert deltas == {}

    def test_false_positive_penalty(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            FakeSignal("FAILURE_MAX_ADVERSE", {"sweep_bool": 1.0, "market_regime": "trending"}),
        ]

        cal = ContraejemploCalibrator(db)
        deltas = cal.analyze_recent_failures(hours_back=24)

        assert "sweep_bool" in deltas
        assert deltas["sweep_bool"] < 0  # penalización negativa

    def test_cooldown_prevents_double_penalty(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            FakeSignal("FAILURE_BEHAVIORAL", {"sweep_bool": 1.0, "market_regime": "trending"}),
            FakeSignal("FAILURE_MAX_ADVERSE", {"sweep_bool": 0.9, "market_regime": "trending"}),
        ]

        cal = ContraejemploCalibrator(db)
        deltas = cal.analyze_recent_failures(hours_back=24)

        # Segunda señal debería ser ignorada por cooldown
        # (mismo feature + mismo regime)
        penalty = deltas["sweep_bool"]
        assert penalty > -0.08  # solo una penalización aplicada, no dos

    def test_apply_rate_limit(self):
        cal = ContraejemploCalibrator(MagicMock())
        cal.weights_delta = {"sweep_bool": -0.15}  # excede límite -10%

        base = {"sweep_bool": 1.0}
        result = cal.apply_to_weights(base)

        # Debe caparse a -10%
        assert result["sweep_bool"] == pytest.approx(0.90, rel=0.01)

    def test_apply_floor_ceiling(self):
        cal = ContraejemploCalibrator(MagicMock())
        cal.weights_delta = {"sweep_bool": -0.50}  # muy negativo

        base = {"sweep_bool": 0.40}
        result = cal.apply_to_weights(base)

        # floor = 0.35
        assert result["sweep_bool"] == pytest.approx(0.35, rel=0.01)

    def test_recovery_for_unpenalized_features(self):
        cal = ContraejemploCalibrator(MagicMock())
        cal.weights_delta = {"sweep_bool": -0.05}

        base = {"sweep_bool": 1.0, "trigger_fvg": 1.0}
        result = cal.apply_to_weights(base)

        # sweep_bool penalizado
        assert result["sweep_bool"] < 1.0
        # trigger_fvg recupera +0.8%
        assert result["trigger_fvg"] == pytest.approx(1.008, rel=0.01)
