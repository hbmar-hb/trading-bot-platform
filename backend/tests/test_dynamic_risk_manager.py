"""Unit tests for Dynamic Risk Manager algorithms.

No DB / exchange required — all evaluators are pure functions.
Run: python -m unittest tests.test_dynamic_risk_manager
"""
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import unittest

from app.services.dynamic_risk_manager import (
    EmergencyBrake,
    ScaleOutProfit,
    TimeDecayExit,
    ExposureCapBySymbol,
)


class FakePosition:
    """Minimal position stand-in for tests."""
    def __init__(self, symbol, side, entry_price, extra=None, timeframe="15m"):
        self.symbol = symbol
        self.side = side
        self.entry_price = Decimal(str(entry_price))
        self.extra_config = extra or {}
        self.timeframe = timeframe
        self.opened_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        self.current_tp_prices = []


class FakeOpenPos:
    def __init__(self, symbol, entry, sl, extra=None):
        self.symbol = symbol
        self.entry_price = Decimal(str(entry))
        self.current_sl_price = Decimal(str(sl))
        self.extra_config = extra or {}


# ═══════════════════════════════════════════════════════════
# Emergency Brake
# ═══════════════════════════════════════════════════════════

class TestEmergencyBrake(unittest.TestCase):
    def test_no_drawdown(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000)
        result = EmergencyBrake.evaluate(pos, Decimal("51000"))
        self.assertEqual(result["action"], "HOLD")

    def test_drawdown_below_threshold(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000)
        result = EmergencyBrake.evaluate(pos, Decimal("49000"))
        self.assertEqual(result["action"], "HOLD")

    def test_drawdown_above_default_threshold(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000)
        result = EmergencyBrake.evaluate(pos, Decimal("47500"))
        self.assertEqual(result["action"], "EMERGENCY_REDUCE")
        self.assertEqual(result["reduce_by"], 0.70)
        self.assertEqual(result["new_sl"], 50000.0)

    def test_doge_low_threshold(self):
        pos = FakePosition("DOGE/USDT:USDT", "long", 0.20)
        result = EmergencyBrake.evaluate(pos, Decimal("0.196"))
        self.assertEqual(result["action"], "EMERGENCY_REDUCE")
        self.assertEqual(result["reduce_by"], 0.80)

    def test_short_drawdown(self):
        pos = FakePosition("BTC/USDT:USDT", "short", 50000)
        result = EmergencyBrake.evaluate(pos, Decimal("52500"))
        self.assertEqual(result["action"], "EMERGENCY_REDUCE")

    def test_already_triggered(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000, extra={"emergency_brake_triggered": True})
        result = EmergencyBrake.evaluate(pos, Decimal("45000"))
        self.assertEqual(result["action"], "HOLD")

    def test_atr_floor(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000)
        # 4% drawdown > 3.5% default, ATR floor = 1.5*1000/50000 = 3%
        result = EmergencyBrake.evaluate(pos, Decimal("48000"), atr_14=Decimal("1000"))
        self.assertEqual(result["action"], "EMERGENCY_REDUCE")


# ═══════════════════════════════════════════════════════════
# Scale-Out Profit
# ═══════════════════════════════════════════════════════════

class TestScaleOutProfit(unittest.TestCase):
    def test_no_profit(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000)
        result = ScaleOutProfit.evaluate(pos, Decimal("49900"))
        self.assertEqual(result["action"], "HOLD")

    def test_first_level(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000)
        result = ScaleOutProfit.evaluate(pos, Decimal("50750"))
        self.assertEqual(result["action"], "SCALE_OUT")
        self.assertEqual(result["level"], 0.01)
        self.assertEqual(result["close_pct"], 0.30)
        self.assertEqual(result["new_sl"], 50000.0)

    def test_second_level(self):
        pos = FakePosition(
            "BTC/USDT:USDT", "long", 50000,
            extra={"scale_out_levels_hit": [0.01]}
        )
        result = ScaleOutProfit.evaluate(pos, Decimal("51500"))
        self.assertEqual(result["action"], "SCALE_OUT")
        self.assertEqual(result["level"], 0.02)
        self.assertEqual(result["close_pct"], 0.20)

    def test_level_already_hit(self):
        pos = FakePosition(
            "BTC/USDT:USDT", "long", 50000,
            extra={"scale_out_levels_hit": [0.01]}
        )
        # +3% profit — 1% already hit, should trigger 2% level
        result = ScaleOutProfit.evaluate(pos, Decimal("51500"))
        self.assertEqual(result["action"], "SCALE_OUT")
        self.assertEqual(result["level"], 0.02)

    def test_short_profit(self):
        pos = FakePosition("BTC/USDT:USDT", "short", 50000)
        result = ScaleOutProfit.evaluate(pos, Decimal("48500"))
        self.assertEqual(result["action"], "SCALE_OUT")
        self.assertEqual(result["level"], 0.01)


# ═══════════════════════════════════════════════════════════
# Time Decay Exit
# ═══════════════════════════════════════════════════════════

class TestTimeDecayExit(unittest.TestCase):
    def test_not_enough_time(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000)
        pos.opened_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        result = TimeDecayExit.evaluate(pos, Decimal("50100"))
        self.assertEqual(result["action"], "HOLD")

    def test_time_exceeded_low_profit(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000, timeframe="15m")
        pos.opened_at = datetime.now(timezone.utc) - timedelta(minutes=150)
        result = TimeDecayExit.evaluate(pos, Decimal("50100"))
        self.assertEqual(result["action"], "TIME_EXIT")
        self.assertIn("time_decay", result["reason"])

    def test_time_exceeded_high_profit(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000, timeframe="15m")
        pos.opened_at = datetime.now(timezone.utc) - timedelta(minutes=150)
        result = TimeDecayExit.evaluate(pos, Decimal("52000"))
        self.assertEqual(result["action"], "PROTECT_PROFIT")
        self.assertIsNotNone(result["new_sl"])

    def test_already_exited(self):
        pos = FakePosition("BTC/USDT:USDT", "long", 50000, extra={"time_decay_exited": True})
        pos.opened_at = datetime.now(timezone.utc) - timedelta(minutes=150)
        result = TimeDecayExit.evaluate(pos, Decimal("50100"))
        self.assertEqual(result["action"], "HOLD")


# ═══════════════════════════════════════════════════════════
# Exposure Cap by Symbol
# ═══════════════════════════════════════════════════════════

class TestExposureCapBySymbol(unittest.TestCase):
    def test_allowed(self):
        result = ExposureCapBySymbol.check("BTC/USDT:USDT", 0.02, [])
        self.assertTrue(result["allowed"])

    def test_blocked(self):
        open_pos = [FakeOpenPos("DOGE/USDT:USDT", 0.20, 0.19, {"initial_risk_pct": 0.015})]
        result = ExposureCapBySymbol.check("DOGE/USDT:USDT", 0.01, open_pos)
        self.assertFalse(result["allowed"])
        self.assertIn("exposure_cap", result["reason"])
        self.assertAlmostEqual(result["max_allowed"], 0.005, places=5)

    def test_doge_cap(self):
        result = ExposureCapBySymbol.check("DOGE/USDT:USDT", 0.025, [])
        self.assertFalse(result["allowed"])

    def test_slippage_multiplier(self):
        result = ExposureCapBySymbol.check("DOGE/USDT:USDT", 0.01, [])
        self.assertEqual(result["slippage_multiplier"], 3.0)

    def test_fallback_risk_calc(self):
        open_pos = [FakeOpenPos("BTC/USDT:USDT", 50000, 49000)]
        result = ExposureCapBySymbol.check("BTC/USDT:USDT", 0.01, open_pos)
        self.assertTrue(result["allowed"])


if __name__ == "__main__":
    unittest.main()
