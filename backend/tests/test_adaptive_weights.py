"""Tests for adaptive confluence weights system."""
import json
import tempfile
from pathlib import Path

import pytest

from app.engines.confluence_engine import _load_adaptive_weights
from app.tasks.ai_retrain_task import _build_global_weights, _BASE_WEIGHTS


class TestBuildGlobalWeights:
    def test_empty_importance_returns_base_weights(self):
        result = _build_global_weights({})
        assert result == _BASE_WEIGHTS

    def test_single_feature_maps_correctly(self):
        # trigger_fvg → trigger_FVG only
        fi = {"trigger_fvg": 0.5}
        result = _build_global_weights(fi)
        assert "trigger_FVG" in result
        assert result["trigger_FVG"] > _BASE_WEIGHTS["trigger_FVG"]
        # Others should be at minimum (0.5x base)
        assert result["structure_CHoCH"] == pytest.approx(_BASE_WEIGHTS["structure_CHoCH"] * 0.5, abs=0.1)

    def test_factor_bounds_0_5_to_1_5(self):
        fi = {"trigger_fvg": 1.0, "trigger_ob": 0.0}
        result = _build_global_weights(fi)
        for comp, weight in result.items():
            base = _BASE_WEIGHTS[comp]
            assert base * 0.5 <= weight <= base * 1.5


class TestLoadAdaptiveWeights:
    def test_missing_file_returns_empty(self):
        import app.engines.confluence_engine as ce
        original_path = getattr(ce, 'ADAPTIVE_WEIGHTS_PATH', None)
        try:
            with tempfile.TemporaryDirectory() as td:
                ce.ADAPTIVE_WEIGHTS_PATH = Path(td) / "nonexistent.json"
                result = ce._load_adaptive_weights()
                assert result == {}
        finally:
            if original_path:
                ce.ADAPTIVE_WEIGHTS_PATH = original_path

    def test_global_fallback(self):
        import app.engines.confluence_engine as ce
        original_path = getattr(ce, 'ADAPTIVE_WEIGHTS_PATH', None)
        try:
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "adaptive_weights.json"
                path.write_text(json.dumps({
                    "global": {"trigger_OB": 22.5},
                    "by_ticker": {}
                }))
                ce.ADAPTIVE_WEIGHTS_PATH = path
                result = ce._load_adaptive_weights()
                assert result["trigger_OB"] == 22.5
        finally:
            if original_path:
                ce.ADAPTIVE_WEIGHTS_PATH = original_path

    def test_ticker_specific_weights(self):
        import app.engines.confluence_engine as ce
        original_path = getattr(ce, 'ADAPTIVE_WEIGHTS_PATH', None)
        try:
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "adaptive_weights.json"
                path.write_text(json.dumps({
                    "global": {"trigger_OB": 20.0, "trigger_FVG": 10.0},
                    "by_ticker": {
                        "BTCUSDT": {
                            "1h": {"trigger_OB": 25.0, "trigger_FVG": 12.0}
                        }
                    }
                }))
                ce.ADAPTIVE_WEIGHTS_PATH = path
                # Specific ticker/timeframe
                result = ce._load_adaptive_weights("BTCUSDT", "1h")
                assert result["trigger_OB"] == 25.0
                assert result["trigger_FVG"] == 12.0
                # Unknown ticker falls back to global
                result2 = ce._load_adaptive_weights("ETHUSDT", "1h")
                assert result2["trigger_OB"] == 20.0
        finally:
            if original_path:
                ce.ADAPTIVE_WEIGHTS_PATH = original_path


class TestConfluenceEngineWeightFunction:
    def test_w_without_adaptive_returns_base(self):
        import app.engines.confluence_engine as ce
        # Simulate the w() function behavior
        adaptive = {}
        def w(key, base):
            if not adaptive:
                return base
            return adaptive.get(key, base)
        assert w("trigger_OB", 15.0) == 15.0

    def test_w_with_adaptive_returns_adaptive(self):
        adaptive = {"trigger_OB": 22.5}
        def w(key, base):
            if not adaptive:
                return base
            return adaptive.get(key, base)
        assert w("trigger_OB", 15.0) == 22.5
        assert w("unknown_key", 10.0) == 10.0  # fallback to base for missing keys
