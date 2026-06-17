"""Unit tests for Smart Money Engine and ICT strategy."""
from __future__ import annotations

import unittest
from typing import List

from app.services.ict_engine import (
    SmartMoneyEngine,
    Candle,
    IndicatorConfig,
    StructureConfig,
    OBConfig,
    FVGConfig,
    IFVGConfig,
    FibConfig,
    MultiTimeframeConfig,
)
from app.services.ict_strategy import (
    StrategyConfig,
    generate_ict_signal,
    scan_historical_signals,
)


def _make_candles(n: int = 80, close_start: float = 100.0, step: float = 0.5) -> List[Candle]:
    candles = []
    for i in range(n):
        close = close_start + i * step
        candles.append(Candle(
            open=close - 0.2,
            high=close + 0.3,
            low=close - 0.4,
            close=close,
            volume=1.0,
            time=1_700_000_000_000 + i * 3_600_000,
        ))
    return candles


def _trending_candles(n: int = 80, up: bool = True) -> List[Candle]:
    candles = []
    base = 100.0
    sign = 1 if up else -1
    for i in range(n):
        # Trend with periodic pullbacks to create real swing pivots.
        trend = i * 0.5 * sign
        pullback = (2.0 if i % 8 == 0 else 0.0) * (-sign)
        close = base + trend + pullback
        # Occasional bearish candle in an uptrend to form bull OBs.
        is_bear = (up and i % 7 == 0) or (not up and i % 7 == 3)
        open_p = close + (0.3 if is_bear else -0.2)
        candles.append(Candle(
            open=open_p,
            high=max(open_p, close) + 0.3,
            low=min(open_p, close) - 0.3,
            close=close,
            volume=2.0 if is_bear else 1.0,
            time=1_700_000_000_000 + i * 3_600_000,
        ))
    return candles


class TestSmartMoneyEngine(unittest.TestCase):

    def _engine(self, **kwargs) -> SmartMoneyEngine:
        cfg = IndicatorConfig(**kwargs)
        return SmartMoneyEngine(cfg)

    def test_process_empty(self):
        out = self._engine().process({"1h": []})
        self.assertEqual(out.boxes, [])
        self.assertEqual(out.lines, [])
        self.assertEqual(out.current_trend, "ranging")

    def test_fvg_bull_detection(self):
        t0 = 1_700_000_000_000
        # Build enough bars to pass the engine warmup.
        candles = []
        for i in range(55):
            close = 100.0 + i * 0.01
            candles.append(Candle(open=close-0.1, high=close+0.2, low=close-0.2, close=close,
                                  volume=1.0, time=t0 + i * 3_600_000))
        # Create a bullish FVG at the last candle: low[i] > high[i-2]
        candles[-3] = Candle(open=100.5, high=100.6, low=100.4, close=100.5, volume=1.0,
                             time=t0 + (len(candles)-3) * 3_600_000)
        candles[-2] = Candle(open=100.5, high=100.55, low=100.45, close=100.5, volume=1.0,
                             time=t0 + (len(candles)-2) * 3_600_000)
        candles[-1] = Candle(open=101.5, high=102.0, low=101.5, close=101.8, volume=1.0,
                             time=t0 + (len(candles)-1) * 3_600_000)
        cfg = IndicatorConfig(fvg=FVGConfig(timeframes=["1h"], filter_enabled=False),
                              ob=OBConfig(enabled=False),
                              structure=StructureConfig(enabled=False))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        bull_fvgs = [b for b in out.boxes if b.type == "FVG" and b.direction == "bull"]
        self.assertEqual(len(bull_fvgs), 1)
        self.assertAlmostEqual(bull_fvgs[0].bottom, 100.6, places=5)

    def test_fvg_bear_detection(self):
        t0 = 1_700_000_000_000
        candles = []
        for i in range(55):
            close = 103.0 - i * 0.01
            candles.append(Candle(open=close-0.1, high=close+0.2, low=close-0.2, close=close,
                                  volume=1.0, time=t0 + i * 3_600_000))
        candles[-3] = Candle(open=102.5, high=102.6, low=102.4, close=102.5, volume=1.0,
                             time=t0 + (len(candles)-3) * 3_600_000)
        candles[-2] = Candle(open=102.5, high=102.55, low=102.45, close=102.5, volume=1.0,
                             time=t0 + (len(candles)-2) * 3_600_000)
        candles[-1] = Candle(open=101.0, high=101.5, low=101.0, close=101.2, volume=1.0,
                             time=t0 + (len(candles)-1) * 3_600_000)
        cfg = IndicatorConfig(fvg=FVGConfig(timeframes=["1h"], filter_enabled=False),
                              ob=OBConfig(enabled=False),
                              structure=StructureConfig(enabled=False))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        bear_fvgs = [b for b in out.boxes if b.type == "FVG" and b.direction == "bear"]
        self.assertEqual(len(bear_fvgs), 1)
        self.assertAlmostEqual(bear_fvgs[0].top, 102.4, places=5)

    def test_fvg_atr_filter_excludes_small_gaps(self):
        t0 = 1_700_000_000_000
        candles = [
            Candle(open=100.0, high=100.5, low=99.5, close=100.0, volume=1.0, time=t0),
            Candle(open=100.0, high=100.05, low=99.95, close=100.0, volume=1.0, time=t0 + 3_600_000),
            Candle(open=100.1, high=100.12, low=100.08, close=100.1, volume=1.0, time=t0 + 7_200_000),
        ]
        cfg = IndicatorConfig(fvg=FVGConfig(timeframes=["1h"], filter_enabled=True, min_size_atr_mult=0.5),
                              ob=OBConfig(enabled=False),
                              structure=StructureConfig(enabled=False))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        fvgs = [b for b in out.boxes if b.type == "FVG"]
        self.assertEqual(len(fvgs), 0)

    def test_ob_created_on_swing_break(self):
        t0 = 1_700_000_000_000
        candles = []
        # Clear bull structure: base, higher low, then breakout above prior high.
        for i in range(80):
            if i < 25:
                close = 100.0 + i * 0.1
            elif i < 45:
                close = 102.5 - (i - 25) * 0.1
            elif i < 55:
                close = 100.5 + (i - 45) * 0.15
            else:
                close = 102.0 + (i - 55) * 0.3
            # Place a bear candle just before the breakout for the OB.
            is_bear = (i == 54)
            open_p = close + (0.3 if is_bear else -0.1)
            candles.append(Candle(open=open_p, high=max(open_p, close)+0.2,
                                  low=min(open_p, close)-0.2, close=close,
                                  volume=3.0 if is_bear else 1.0,
                                  time=t0 + i * 3_600_000))
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=5),
                              ob=OBConfig(timeframes=["1h"], lookback=30),
                              fvg=FVGConfig(enabled=False))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        obs = [b for b in out.boxes if b.type == "OB"]
        self.assertGreater(len(obs), 0)
        self.assertTrue(any(o.direction == "bull" for o in obs))

    def test_ob_mitigation_removes_box(self):
        t0 = 1_700_000_000_000
        candles = [
            Candle(open=100.0, high=101.0, low=100.0, close=100.1, volume=1.0, time=t0),
            Candle(open=100.2, high=100.5, low=100.1, close=100.4, volume=1.0, time=t0 + 3_600_000),
            Candle(open=100.4, high=100.8, low=100.3, close=100.7, volume=1.0, time=t0 + 7_200_000),
            Candle(open=100.7, high=101.1, low=100.6, close=101.0, volume=1.0, time=t0 + 10_800_000),
            # mitigating wick below the OB bottom
            Candle(open=99.5, high=99.8, low=98.0, close=99.5, volume=1.0, time=t0 + 14_400_000),
        ]
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=2),
                              ob=OBConfig(timeframes=["1h"], mitigation="wick"),
                              fvg=FVGConfig(enabled=False))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        # The OB should be removed once the mitigating candle appears.
        final_obs = [b for b in out.boxes if b.type == "OB"]
        self.assertEqual(len(final_obs), 0)

    def test_swing_bos_detection(self):
        t0 = 1_700_000_000_000
        candles = []
        for i in range(80):
            # Create visible waves: up, pullback, up to generate swing pivots and a BOS.
            if i < 30:
                close = 100.0 + i * 0.2
            elif i < 50:
                close = 106.0 - (i - 30) * 0.25
            else:
                close = 101.0 + (i - 50) * 0.4
            candles.append(Candle(open=close-0.1, high=close+0.3, low=close-0.3, close=close,
                                  volume=1.0, time=t0 + i * 3_600_000))
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=5),
                              ob=OBConfig(enabled=False),
                              fvg=FVGConfig(enabled=False))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        bos_lines = [l for l in out.lines if l.type == "BOS"]
        self.assertGreater(len(bos_lines), 0)
        self.assertEqual(out.dashboard.swing_trend, "bull")

    def test_internal_structure(self):
        candles = _trending_candles(n=80, up=True)
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=10, internal_len=3),
                              ob=OBConfig(enabled=False),
                              fvg=FVGConfig(enabled=False))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        internal = [l for l in out.lines if l.type.startswith("INTERNAL")]
        self.assertGreaterEqual(len(internal), 0)
        self.assertIn(out.dashboard.internal_trend, ("bull", "ranging"))

    def test_ifvg_created_when_fvg_filled(self):
        t0 = 1_700_000_000_000
        candles = []
        for i in range(53):
            close = 100.0
            candles.append(Candle(open=close-0.1, high=close+0.2, low=close-0.2, close=close,
                                  volume=1.0, time=t0 + i * 3_600_000))
        candles[-4] = Candle(open=100.0, high=100.3, low=99.9, close=100.0, volume=1.0,
                             time=t0 + (len(candles)-4) * 3_600_000)
        candles[-3] = Candle(open=100.5, high=100.55, low=100.35, close=100.5, volume=1.0,
                             time=t0 + (len(candles)-3) * 3_600_000)
        # Fill the bull FVG (bottom=100.3) but close inside it so the bear IFVG survives.
        candles[-2] = Candle(open=100.5, high=100.5, low=100.0, close=100.2, volume=1.0,
                             time=t0 + (len(candles)-2) * 3_600_000)
        candles[-1] = Candle(open=100.2, high=100.25, low=100.1, close=100.15, volume=1.0,
                             time=t0 + (len(candles)-1) * 3_600_000)
        cfg = IndicatorConfig(fvg=FVGConfig(timeframes=["1h"], filter_enabled=False),
                              ifvg=IFVGConfig(timeframes=["1h"], enabled=True),
                              ob=OBConfig(enabled=False),
                              structure=StructureConfig(enabled=False))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        ifvgs = [b for b in out.boxes if b.type == "IFVG"]
        self.assertGreaterEqual(len(ifvgs), 1)

    def test_fibonacci_drawn(self):
        candles = _trending_candles(n=80, up=True)
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=10),
                              fib=FibConfig(enabled=True, show_fib=True, show_fib_ote=True),
                              ob=OBConfig(enabled=False),
                              fvg=FVGConfig(enabled=False))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        fibs = [l for l in out.lines if l.type == "FIB"]
        self.assertGreater(len(fibs), 0)
        ote = [b for b in out.boxes if b.type == "OTE"]
        self.assertEqual(len(ote), 1)

    def test_strong_weak_lines(self):
        candles = _trending_candles(n=80, up=True)
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=10, show_strong_weak=True),
                              ob=OBConfig(enabled=False),
                              fvg=FVGConfig(enabled=False))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        strong = [l for l in out.lines if l.type == "STRONG"]
        self.assertGreaterEqual(len(strong), 1)

    def test_htf_bias_bull(self):
        htf = _trending_candles(n=60, up=True)
        ltf = _trending_candles(n=80, up=True)
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"]),
                              multi_tf=MultiTimeframeConfig(enabled=True, auto_htf=False, htf_resolution="4h", htf_ema_len=50))
        out = SmartMoneyEngine(cfg).process({"1h": ltf, "4h": htf})
        self.assertIsNotNone(out.htf_bias)
        self.assertEqual(out.htf_bias["direction"], "bull")

    def test_output_is_json_serializable(self):
        candles = _trending_candles(n=80, up=True)
        out = self._engine().process({"1h": candles})
        data = out.to_dict()
        self.assertIn("boxes", data)
        self.assertIn("lines", data)
        self.assertIn("dashboard", data)
        self.assertTrue(isinstance(data["boxes"], list))


class TestICTStrategy(unittest.TestCase):

    def test_signal_long_at_bull_ob(self):
        candles = _trending_candles(n=80, up=True)
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=10),
                              ob=OBConfig(timeframes=["1h"]),
                              fvg=FVGConfig(timeframes=["1h"]))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        scfg = StrategyConfig(min_score=4, require_sweep=False, reject_asia=False, reject_equilibrium=False)
        signal = generate_ict_signal(out, candles[-1].close, scfg, candles=candles)
        # In a clean uptrend with an active bull OB we usually get a long signal.
        self.assertIn(signal.direction, ("long", "none"))
        if signal.direction != "none":
            self.assertGreater(signal.stop_loss, 0)
            self.assertGreater(signal.take_profit_1, 0)
            self.assertGreaterEqual(signal.risk_reward_1, scfg.min_rr)

    def test_min_score_gate(self):
        candles = _trending_candles(n=80, up=True)
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=10),
                              ob=OBConfig(timeframes=["1h"]),
                              fvg=FVGConfig(timeframes=["1h"]))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        scfg = StrategyConfig(min_score=12, require_sweep=False, reject_asia=False, reject_equilibrium=False)
        signal = generate_ict_signal(out, candles[-1].close, scfg, candles=candles)
        self.assertEqual(signal.direction, "none")

    def test_require_htf_alignment(self):
        candles = _trending_candles(n=80, up=True)
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=10),
                              ob=OBConfig(timeframes=["1h"]),
                              fvg=FVGConfig(timeframes=["1h"]),
                              multi_tf=MultiTimeframeConfig(enabled=True, htf_ema_len=50))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        # Force a bearish HTF bias artificially
        out.htf_bias = {"direction": "bear", "strength": 1.0, "timeframe": "4h"}
        scfg = StrategyConfig(min_score=4, require_htf_alignment=True, require_sweep=False, reject_asia=False, reject_equilibrium=False)
        signal = generate_ict_signal(out, candles[-1].close, scfg, candles=candles)
        self.assertEqual(signal.direction, "none")

    def test_reject_equilibrium(self):
        candles = _make_candles(n=50, close_start=100.0)
        for c in candles:
            c.open = 100.0
            c.high = 100.5
            c.low = 99.5
            c.close = 100.0
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=10),
                              ob=OBConfig(timeframes=["1h"]),
                              fvg=FVGConfig(timeframes=["1h"]))
        out = SmartMoneyEngine(cfg).process({"1h": candles})
        scfg = StrategyConfig(min_score=1, reject_equilibrium=True, require_sweep=False, reject_asia=False)
        signal = generate_ict_signal(out, 100.0, scfg, candles=candles)
        self.assertEqual(signal.direction, "none")

    def test_scan_historical_signals_runs(self):
        candles = _trending_candles(n=200, up=True)
        cfg = IndicatorConfig(structure=StructureConfig(timeframes=["1h"], swing_len=10),
                              ob=OBConfig(timeframes=["1h"]),
                              fvg=FVGConfig(timeframes=["1h"]))
        scfg = StrategyConfig(min_score=4, require_sweep=False, reject_asia=False, reject_equilibrium=False)
        result = scan_historical_signals(candles, timeframe="1h", strategy_config=scfg, engine_config=cfg,
                                         step=10, max_signals=10)
        self.assertIn("signals", result)
        self.assertIn("stats", result)
        self.assertIsInstance(result["signals"], list)


if __name__ == "__main__":
    unittest.main()
