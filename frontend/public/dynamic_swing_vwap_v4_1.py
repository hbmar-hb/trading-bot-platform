#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DYNAMIC SWING VWAP v4.1 - Correcciones de Backtesting
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from enum import Enum


class TrendDirection(Enum):
    BEARISH = -1
    NEUTRAL = 0
    BULLISH = 1


@dataclass
class VWAPConfig:
    swing_lookback: int = 20
    base_apt: float = 21.0
    adapt_apt_by_atr: bool = True
    volatility_bias: float = 2.0
    vwap_source: str = "close"
    cap_volume_spikes: bool = True
    smooth_anchor_ramp: bool = True
    only_ll_hh_anchors: bool = True
    min_bars_between_anchors: int = 10
    show_bands: bool = True
    band_multiplier: float = 0.618
    show_signals: bool = True
    max_atr_dist_to_band: float = 0.3
    band_touch_lookback: int = 5
    # NUEVOS PARAMETROS
    trend_ema_period: int = 50
    min_atr_dist_to_vwap: float = 0.3
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5


class DynamicSwingVWAP:
    def __init__(self, df: pd.DataFrame, config: Optional[VWAPConfig] = None):
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        self.df = df.copy()
        self.config = config or VWAPConfig()
        self.n = len(df)
        self._reset_state()

    def _reset_state(self):
        self.p = np.nan
        self.vol = np.nan
        self.current_vwap = np.nan
        self.seg_atr = np.nan
        self.seg_start_bar = -1
        self.seg_start_price = np.nan
        self.anchored_dir = 1
        # FIX: Inicializar a np.nan, no -1
        self.ph = np.nan
        self.pl = np.nan
        self.phL = np.nan
        self.plL = np.nan
        # FIX: Tendencia independiente de anchored_dir
        self.trend_dir = 0
        self.last_anchor_bar = -9999
        self.last_swing_str = "—"
        self.prev_high = np.nan
        self.prev_low = np.nan
        self.frozen_vwap_segments = []
        self.frozen_upper_segments = []
        self.frozen_lower_segments = []

    def _get_source(self, i: int) -> float:
        return self.df[self.config.vwap_source].iloc[i]

    def _alpha_from_apt(self, apt: float) -> float:
        return 1.0 - np.exp(-np.log(2.0) / max(1.0, apt))

    def _detect_swing_high(self, i: int) -> bool:
        if i < self.config.swing_lookback:
            return False
        window = self.df['high'].iloc[i - self.config.swing_lookback + 1:i + 1]
        current_high = self.df['high'].iloc[i]
        is_highest = current_high == window.max()
        prev_diff = current_high != self.df['high'].iloc[i - 1] if i > 0 else True
        return is_highest and prev_diff

    def _detect_swing_low(self, i: int) -> bool:
        if i < self.config.swing_lookback:
            return False
        window = self.df['low'].iloc[i - self.config.swing_lookback + 1:i + 1]
        current_low = self.df['low'].iloc[i]
        is_lowest = current_low == window.min()
        prev_diff = current_low != self.df['low'].iloc[i - 1] if i > 0 else True
        return is_lowest and prev_diff

    def _calculate_atr(self, i: int, period: int = 14) -> float:
        if i < period:
            return np.nan
        highs = self.df['high'].iloc[i - period + 1:i + 1]
        lows = self.df['low'].iloc[i - period + 1:i + 1]
        closes_prev = self.df['close'].iloc[i - period:i]
        tr1 = highs.values - lows.values
        tr2 = np.abs(highs.values - closes_prev.values)
        tr3 = np.abs(lows.values - closes_prev.values)
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        return np.mean(tr)

    def _calculate_atr_rma(self, i: int, period: int = 14) -> float:
        if i < period * 2:
            return self._calculate_atr(i, period)
        atr_values = []
        for j in range(i - period + 1, i + 1):
            atr_values.append(self._calculate_atr(j, period))
        alpha = 1.0 / period
        rma = atr_values[0]
        for val in atr_values[1:]:
            if not np.isnan(val):
                rma = alpha * val + (1 - alpha) * rma
        return rma

    def _process_volume(self, i: int) -> float:
        if i < 50:
            return max(self.df['volume'].iloc[i], 1.0)
        volume_window = self.df['volume'].iloc[i - 50:i + 1]
        vol_median = np.median(volume_window)
        vol_sma20 = np.mean(self.df['volume'].iloc[i - 19:i + 1])
        vol_cap = max(vol_sma20 * 3.0, 1.0)
        raw_vol = self.df['volume'].iloc[i]
        floor_vol = raw_vol if raw_vol > 0 else vol_median
        if self.config.cap_volume_spikes:
            return max(min(floor_vol, vol_cap), 1.0)
        return max(floor_vol, 1.0)

    def _calculate_apt(self, i: int, atr: float, atr_avg: float) -> float:
        if not self.config.adapt_apt_by_atr or atr_avg <= 0:
            return self.config.base_apt
        ratio = atr / atr_avg if atr_avg > 0 else 1.0
        log_ratio = np.log(max(ratio, 0.1))
        apt_raw = self.config.base_apt * (1.0 + log_ratio * self.config.volatility_bias * 0.1)
        return max(5.0, min(100.0, apt_raw))

    def _get_swing_label(self, is_high: bool, price: float) -> str:
        if is_high:
            if np.isnan(self.prev_high):
                return "IH"
            elif price > self.prev_high:
                return "HH"
            elif price < self.prev_high:
                return "LH"
            else:
                return "EH"
        else:
            if np.isnan(self.prev_low):
                return "IL"
            elif price < self.prev_low:
                return "LL"
            elif price > self.prev_low:
                return "HL"
            else:
                return "EL"

    def calculate(self) -> pd.DataFrame:
        self._reset_state()

        vwap_arr = np.full(self.n, np.nan)
        upper_band_arr = np.full(self.n, np.nan)
        lower_band_arr = np.full(self.n, np.nan)
        trend_dir_arr = np.full(self.n, 0)
        swing_label_arr = np.full(self.n, "—", dtype=object)
        buy_signal_arr = np.full(self.n, False)
        sell_signal_arr = np.full(self.n, False)
        atr_arr = np.full(self.n, np.nan)
        apt_arr = np.full(self.n, np.nan)

        for i in range(self.n):
            high = self.df['high'].iloc[i]
            low = self.df['low'].iloc[i]
            close = self.df['close'].iloc[i]
            src = self._get_source(i)

            is_swing_high = self._detect_swing_high(i)
            is_swing_low = self._detect_swing_low(i)
            swing_label = ""

            if is_swing_high:
                self.ph = high
                self.phL = i
                swing_label = self._get_swing_label(True, high)
                self.prev_high = high
                self.last_swing_str = swing_label
                # FIX: Actualizar trend_dir por estructura de mercado
                if swing_label == "HH":
                    self.trend_dir = 1
                elif swing_label == "LH":
                    self.trend_dir = -1

            if is_swing_low:
                self.pl = low
                self.plL = i
                swing_label = self._get_swing_label(False, low)
                self.prev_low = low
                self.last_swing_str = swing_label
                # FIX: Actualizar trend_dir por estructura de mercado
                if swing_label == "HL":
                    self.trend_dir = 1
                elif swing_label == "LL":
                    self.trend_dir = -1

            # FIX: dir_val solo cuando AMBOS swings existen
            dir_val = 0
            if not np.isnan(self.phL) and not np.isnan(self.plL):
                dir_val = 1 if self.phL > self.plL else -1

            current_bar_vol = self._process_volume(i)
            atr = self._calculate_atr(i)
            atr_avg = self._calculate_atr_rma(i) if i >= 14 else atr
            atr_arr[i] = atr

            apt = self._calculate_apt(i, atr, atr_avg)
            apt_arr[i] = apt

            should_anchor = False
            new_anchor_dir = 0

            if i > 0:
                prev_dir = trend_dir_arr[i - 1]
                if dir_val != 0 and prev_dir != 0 and dir_val != prev_dir:
                    bars_since_last = i - self.last_anchor_bar
                    if bars_since_last >= self.config.min_bars_between_anchors:
                        if self.config.only_ll_hh_anchors:
                            should_anchor = (swing_label in ["LL", "HH", "IL", "IH"])
                        else:
                            should_anchor = True
                        if should_anchor:
                            new_anchor_dir = dir_val

            if should_anchor:
                if not np.isnan(self.current_vwap):
                    self.frozen_vwap_segments.append({
                        'start_bar': self.seg_start_bar,
                        'end_bar': i,
                        'start_price': self.seg_start_price,
                        'end_price': self.current_vwap,
                        'direction': self.anchored_dir
                    })
                if len(self.frozen_vwap_segments) > 30:
                    self.frozen_vwap_segments.pop(0)

                self.anchored_dir = new_anchor_dir
                self.seg_start_bar = i
                self.seg_start_price = src
                self.p = src * current_bar_vol
                self.vol = current_bar_vol
                self.seg_atr = atr
                self.last_anchor_bar = i
                self.current_vwap = src

            elif np.isnan(self.p):
                init_dir = dir_val if dir_val != 0 else 1
                self.anchored_dir = init_dir
                self.seg_start_bar = i
                self.seg_start_price = src
                self.p = src * current_bar_vol
                self.vol = current_bar_vol
                self.seg_atr = atr
                self.last_anchor_bar = i
                self.current_vwap = src

            else:
                if not self.config.only_ll_hh_anchors and dir_val != 0:
                    self.anchored_dir = dir_val
                a = self._alpha_from_apt(apt)
                if self.config.smooth_anchor_ramp and self.seg_start_bar >= 0:
                    bars_from_start = i - self.seg_start_bar
                    if bars_from_start < 5:
                        a = a * (0.5 + 0.5 * (bars_from_start + 1) / 5.0)
                self.p = (1.0 - a) * self.p + a * (src * current_bar_vol)
                self.vol = (1.0 - a) * self.vol + a * current_bar_vol
                self.current_vwap = self.p / self.vol if self.vol > 0 else np.nan

            if self.config.show_bands and not np.isnan(self.current_vwap) and not np.isnan(self.seg_atr):
                dev = self.seg_atr * self.config.band_multiplier
                upper_band_arr[i] = self.current_vwap + dev
                lower_band_arr[i] = self.current_vwap - dev

            vwap_arr[i] = self.current_vwap
            trend_dir_arr[i] = self.anchored_dir
            swing_label_arr[i] = self.last_swing_str

            if i > 0 and self.config.show_signals:
                prev_close = self.df['close'].iloc[i - 1]
                prev_vwap = vwap_arr[i - 1]
                cross_above = prev_close < prev_vwap and close >= self.current_vwap
                cross_below = prev_close > prev_vwap and close <= self.current_vwap

                touch_thresh = atr * self.config.max_atr_dist_to_band if not np.isnan(atr) else 0
                lower_band_touched = False
                upper_band_touched = False

                lookback = min(self.config.band_touch_lookback, i)
                for j in range(1, lookback + 1):
                    idx = i - j
                    if not np.isnan(lower_band_arr[idx]):
                        if abs(self.df['low'].iloc[idx] - lower_band_arr[idx]) <= touch_thresh:
                            lower_band_touched = True
                    if not np.isnan(upper_band_arr[idx]):
                        if abs(self.df['high'].iloc[idx] - upper_band_arr[idx]) <= touch_thresh:
                            upper_band_touched = True

                bull_swing_recent = False
                bear_swing_recent = False
                for j in range(0, min(self.config.band_touch_lookback, i) + 1):
                    sl = swing_label_arr[i - j]
                    if sl in ["HL", "LL", "IL"]:
                        bull_swing_recent = True
                    if sl in ["LH", "HH", "IH"]:
                        bear_swing_recent = True

                # FIX: Usar self.trend_dir en lugar de self.anchored_dir
                dir_bull = self.trend_dir == 1
                dir_bear = self.trend_dir == -1

                # FIX: Distancia minima al VWAP
                min_dist = atr * self.config.min_atr_dist_to_vwap if not np.isnan(atr) else 0
                vwap_dist_bull = (close - self.current_vwap) >= min_dist if not np.isnan(self.current_vwap) else False
                vwap_dist_bear = (self.current_vwap - close) >= min_dist if not np.isnan(self.current_vwap) else False

                buy_signal_arr[i] = (
                    cross_above and lower_band_touched and bull_swing_recent
                    and dir_bull and vwap_dist_bull
                )
                sell_signal_arr[i] = (
                    cross_below and upper_band_touched and bear_swing_recent
                    and dir_bear and vwap_dist_bear
                )

                # FIX: Prioridad de señal
                if buy_signal_arr[i] and sell_signal_arr[i]:
                    if self.trend_dir == 1:
                        sell_signal_arr[i] = False
                    elif self.trend_dir == -1:
                        buy_signal_arr[i] = False
                    else:
                        buy_signal_arr[i] = False
                        sell_signal_arr[i] = False

        result = pd.DataFrame({
            'vwap': vwap_arr,
            'upper_band': upper_band_arr,
            'lower_band': lower_band_arr,
            'trend_dir': trend_dir_arr,
            'swing_label': swing_label_arr,
            'buy_signal': buy_signal_arr,
            'sell_signal': sell_signal_arr,
            'atr': atr_arr,
            'apt': apt_arr
        }, index=self.df.index)

        return result


# ==========================================================
# FUNCION REQUERIDA POR EL MOTOR DE BACKTESTING
# ==========================================================

def strategy(df, params):
    config = VWAPConfig(
        swing_lookback=params.get("swing_lookback", 20),
        base_apt=params.get("base_apt", 21.0),
        adapt_apt_by_atr=params.get("adapt_apt_by_atr", True),
        volatility_bias=params.get("volatility_bias", 2.0),
        band_multiplier=params.get("band_multiplier", 0.618),
        show_signals=params.get("show_signals", True),
        max_atr_dist_to_band=params.get("max_atr_dist_to_band", 0.3),
        band_touch_lookback=params.get("band_touch_lookback", 5),
        min_bars_between_anchors=params.get("min_bars_between_anchors", 10),
        trend_ema_period=params.get("trend_ema_period", 50),
        min_atr_dist_to_vwap=params.get("min_atr_dist_to_vwap", 0.3),
        sl_atr_mult=params.get("sl_atr_mult", 1.5),
        tp_atr_mult=params.get("tp_atr_mult", 2.5),
    )

    # FIX: Filtro EMA de tendencia
    ema_trend = df['close'].ewm(span=config.trend_ema_period, adjust=False).mean()

    indicator = DynamicSwingVWAP(df, config)
    result = indicator.calculate()

    signal = pd.Series(0, index=df.index, dtype=int)
    stop_loss = pd.Series(np.nan, index=df.index)
    take_profit = pd.Series(np.nan, index=df.index)

    for i in range(len(df)):
        if result['buy_signal'].iloc[i]:
            # Solo LONG si precio esta por encima de la EMA de tendencia
            if df['close'].iloc[i] > ema_trend.iloc[i]:
                signal.iloc[i] = 1
                atr_val = result['atr'].iloc[i]
                if not np.isnan(atr_val):
                    stop_loss.iloc[i] = df['close'].iloc[i] - atr_val * config.sl_atr_mult
                    take_profit.iloc[i] = df['close'].iloc[i] + atr_val * config.tp_atr_mult

        elif result['sell_signal'].iloc[i]:
            # Solo SHORT si precio esta por debajo de la EMA de tendencia
            if df['close'].iloc[i] < ema_trend.iloc[i]:
                signal.iloc[i] = -1
                atr_val = result['atr'].iloc[i]
                if not np.isnan(atr_val):
                    stop_loss.iloc[i] = df['close'].iloc[i] + atr_val * config.sl_atr_mult
                    take_profit.iloc[i] = df['close'].iloc[i] - atr_val * config.tp_atr_mult

    return pd.DataFrame({
        "signal": signal,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "vwap": result['vwap'],
        "upper_band": result['upper_band'],
        "lower_band": result['lower_band'],
        "trend_dir": result['trend_dir'],
    })
