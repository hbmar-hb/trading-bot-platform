"""Unit tests for LLM client and signal diagnosis.

Run: python -m unittest tests.test_llm_client -v
"""
import json
import unittest
from unittest.mock import patch, MagicMock

from pydantic import BaseModel

from app.services.llm_client import generate_structured, LLMError
from app.services.signal_diagnosis import (
    SignalDiagnosis,
    DiagnosisFactor,
    build_prompt,
    _render_anti_fake_prompt,
)


class FakeSignal:
    def __init__(self):
        self.id = "test-uuid"
        self.ticker = "BTCUSDT"
        self.direction = "long"
        self.timeframe = "1h"
        self.score = 75.0
        self.quality_tier = "STRONG"
        self.anti_fake_status = "BLOCK"
        self.success_probability = 0.78
        self.features = {"volume_ratio": 0.3, "spread_atr": 2.5}
        self.components = {"structure": "CHoCH"}
        self.warnings = ["bajo volumen"]
        self.red_flags = ["Volumen 0.3x — falta de interés del mercado"]
        self.green_flags = ["Liquidity sweep BSL confirmado"]


class TestLLMClient(unittest.TestCase):

    @patch("app.services.llm_client.settings")
    def test_disabled_llm(self, mock_settings):
        mock_settings.llm_enabled = False
        mock_settings.openrouter_api_key = "test-key"

        class DummyModel(BaseModel):
            text: str

        with self.assertRaises(LLMError) as ctx:
            generate_structured("hello", DummyModel)
        self.assertIn("disabled", str(ctx.exception).lower())

    @patch("app.services.llm_client.settings")
    def test_missing_api_key(self, mock_settings):
        mock_settings.llm_enabled = True
        mock_settings.openrouter_api_key = ""

        class DummyModel(BaseModel):
            text: str

        with self.assertRaises(LLMError) as ctx:
            generate_structured("hello", DummyModel)
        self.assertIn("not set", str(ctx.exception).lower())

    @patch("app.services.llm_client._call_llm_sync")
    @patch("app.services.llm_client.settings")
    def test_successful_generation(self, mock_settings, mock_call):
        mock_settings.llm_enabled = True
        mock_settings.openrouter_api_key = "test-key"
        mock_settings.llm_default_model = "test-model"
        mock_settings.llm_fallback_model = "fallback-model"
        mock_settings.llm_max_tokens = 500

        mock_call.return_value = MagicMock(
            content='{"verdict": "BLOCK", "confidence": 85, "summary": "test", "factors": [], "recommendation": "wait"}',
            model_used="test-model",
            latency_ms=1200,
            cost_usd=0.01,
            prompt_tokens=150,
            completion_tokens=50,
        )

        parsed, meta = generate_structured("prompt", SignalDiagnosis)
        self.assertEqual(parsed.verdict, "BLOCK")
        self.assertEqual(parsed.confidence, 85)
        self.assertEqual(meta.model_used, "test-model")

    @patch("app.services.llm_client._call_llm_sync")
    @patch("app.services.llm_client.settings")
    def test_markdown_code_block_stripping(self, mock_settings, mock_call):
        mock_settings.llm_enabled = True
        mock_settings.openrouter_api_key = "test-key"
        mock_settings.llm_default_model = "test-model"
        mock_settings.llm_fallback_model = "fallback-model"
        mock_settings.llm_max_tokens = 500

        mock_call.return_value = MagicMock(
            content='```json\n{"verdict": "CAUTION", "confidence": 60, "summary": "test", "factors": [], "recommendation": "reduce"}\n```',
            model_used="test-model",
            latency_ms=1000,
            cost_usd=0.005,
            prompt_tokens=100,
            completion_tokens=40,
        )

        parsed, _ = generate_structured("prompt", SignalDiagnosis)
        self.assertEqual(parsed.verdict, "CAUTION")


class TestSignalDiagnosis(unittest.TestCase):

    def test_build_prompt_anti_fake(self):
        signal = FakeSignal()
        prompt = build_prompt(signal, "anti_fake")
        self.assertIn("BTCUSDT", prompt)
        self.assertIn("BLOCK", prompt)
        self.assertIn("volume_ratio", prompt)

    def test_build_prompt_gate(self):
        signal = FakeSignal()
        prompt = build_prompt(signal, "gate_kelly", gate_details={"reason": "edge too low"})
        self.assertIn("KELLY", prompt)
        self.assertIn("edge too low", prompt)

    def test_render_anti_fake_prompt(self):
        signal = FakeSignal()
        prompt = _render_anti_fake_prompt(signal, signal.features)
        self.assertIn("0.3", prompt)
        self.assertIn("2.5", prompt)


if __name__ == "__main__":
    unittest.main()
