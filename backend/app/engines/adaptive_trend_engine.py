"""Adaptive Trend Pro — trend-following engine based on ATR trailing stops.

Python port of the TradingView Pine Script strategy "Adaptive Trend Pro".
Integrates with the ICT+SMC confluence engine as a directional filter and
feature source.

Logic:
  1. ATR-based trailing stop with market+TF adaptive parameters
  2. Dynamic multiplier tightens when RSI is in momentum zone (>30 from 50)
  3. Trend = 1 when price > trailing stop (bullish), -1 otherwise
  4. Raw signal on trend flip; confirmed signal when all filters pass
  5. Composite score 0-100 based on RSI, volume, ADX alignment

Filters (optional):
  - RSI momentum: LONG requires RSI > threshold, SHORT requires RSI < 100-threshold
  - Volume: current volume > SMA(20) * threshold
  - ADX: ADX > threshold (auto-enabled for LTF crypto/forex)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from app.engines.smc_engine import compute_atr, compute_adx


# ── Preset matrices (market × timeframe) ─────────────────────────────────────
# Markets: 0=Crypto, 1=Crypto Altcoins, 2=Crypto Memecoins, 3=Forex,
#          4=Stocks, 5=Futures
# TFs: 0=1m, 1=5m, 2=15m, 3=1h, 4=4h, 5=1d

_VOL_LENGTH = {
    0: [5, 7, 8, 10, 12, 14],
    1: [6, 8, 10, 12, 14, 16],
    2: [6, 8, 10, 12, 14, 16],
    3: [5, 7, 10, 14, 16, 20],
    4: [6, 8, 10, 14, 16, 20],
    5: [6, 8, 10, 12, 16, 18],
}

_MULT = {
    0: [1.2, 1.5, 1.8, 2.2, 2.5, 2.8],
    1: [1.4, 1.7, 2.0, 2.5, 2.8, 3.2],
    2: [1.5, 1.9, 2.5, 3.0, 3.5, 4.0],
    3: [1.0, 1.2, 1.8, 2.0, 2.2, 2.5],
    4: [1.2, 1.5, 1.8, 2.2, 2.5, 3.0],
    5: [1.3, 1.6, 2.0, 2.5, 2.8, 3.2],
}

_RSI_LENGTH = [7, 10, 12, 14, 16, 20]

_VOL_THRESHOLD = {0: 1.2, 1: 1.3, 2: 1.3, 3: 1.0, 4: 1.1, 5: 1.2}
_ADX_THRESHOLD = {0: 18.0, 1: 18.0, 2: 15.0, 3: 20.0, 4: 22.0, 5: 20.0}
_RSI_BUY_THRESH = {0: 48.0, 1: 48.0, 2: 45.0, 3: 45.0, 4: 45.0, 5: 45.0}

_TF_SECONDS_MAP = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400,
    "30m": 1800, "2h": 7200, "6h": 21600, "8h": 28800, "12h": 43200,
    "3d": 259200, "1w": 604800,
}


def _detect_market(ticker: str) -> int:
    """Map ticker to market index."""
    t = ticker.upper()
    # Memecoins heuristic
    memes = {"DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "BOME", "FARTCOIN",
             "MOG", "POPCAT", "BRETT", "SLERF", "MYRO", "WEN", "MICHI", "TURBO",
             "PONKE", "ANALOS", "BODEN", "TREMP"}
    if any(m in t for m in memes):
        return 2
    # Altcoins (non-BTC, non-ETH, non-stable)
    majors = {"BTC", "ETH", "XBT", "ETHEREUM"}
    if not any(m in t for m in majors):
        return 1
    return 0


def _tf_idx(timeframe: str) -> int:
    """Map timeframe string to preset index."""
    mapping = {
        "1m": 0, "5m": 1, "15m": 2, "30m": 2,
        "1h": 3, "2h": 3, "4h": 4, "6h": 4, "8h": 4, "12h": 4,
        "1d": 5, "3d": 5, "1w": 5,
    }
    return mapping.get(timeframe, 2)


def _rsi(series: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def _dmi(df: pd.DataFrame, period: int = 14) -> tuple[float, float, float]:
    """Return (dmi_plus, dmi_minus, adx) as last values."""
    h, l, c = df["high"], df["low"], df["close"]
    prev_h, prev_l, prev_c = h.shift(1), l.shift(1), c.shift(1)

    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    pdm_raw = np.where((h - prev_h) > (prev_l - l), np.maximum(h - prev_h, 0), 0)
    mdm_raw = np.where((prev_l - l) > (h - prev_h), np.maximum(prev_l - l, 0), 0)
    pdm = pd.Series(pdm_raw, index=df.index, dtype=float)
    mdm = pd.Series(mdm_raw, index=df.index, dtype=float)

    atr_smoothed = tr.ewm(alpha=1 / period, min_periods=period).mean()
    pdi = 100 * pdm.ewm(alpha=1 / period, min_periods=period).mean() / atr_smoothed.replace(0, 1e-10)
    mdi = 100 * mdm.ewm(alpha=1 / period, min_periods=period).mean() / atr_smoothed.replace(0, 1e-10)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, 1e-10)
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()

    return float(pdi.iloc[-1]), float(mdi.iloc[-1]), float(adx.iloc[-1])


@dataclass
class AdaptiveTrendResult:
    trend: int                        # 1 = bullish, -1 = bearish
    trailing_stop: float
    raw_signal: bool                  # trend flipped this candle
    confirmed_signal: bool            # trend flipped + filters passed
    signal_direction: Optional[str]   # "long" | "short" | None
    composite_score: float            # 0-100
    rsi: float
    adx: float
    volume_ratio: float               # current / SMA(20)
    atr: float
    hybrid_vol: float
    dynamic_mult: float
    filters_passed: bool
    # Features for ML / downstream use
    features: dict = field(default_factory=dict)


def analyze_adaptive_trend(
    candles: list[dict],
    ticker: str,
    timeframe: str,
    price_src_col: str = "hlc3",
    use_momentum_filter: bool = True,
    use_volume_filter: bool = True,
    use_adx_filter: bool = False,
    tighten_on_momentum: bool = True,
    adaptive_vol_smoothing: bool = True,
) -> Optional[AdaptiveTrendResult]:
    """Run Adaptive Trend Pro analysis on OHLCV candles.

    Args:
        candles: list of {open, high, low, close, volume} dicts.
        ticker: symbol like "BTCUSDT".
        timeframe: "15m", "1h", etc.
        price_src_col: "hlc3" (default), "close", "ohlc4", etc.
    Returns:
        AdaptiveTrendResult or None if insufficient data.
    """
    if len(candles) < 50:
        return None

    df = pd.DataFrame(candles)[["open", "high", "low", "close", "volume"]].astype(float)
    df = df.reset_index(drop=True)

    # Build price source
    if price_src_col == "hlc3":
        price_src = (df["high"] + df["low"] + df["close"]) / 3.0
    elif price_src_col == "ohlc4":
        price_src = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    else:
        price_src = df["close"]

    # ── Preset params ──
    m_idx = _detect_market(ticker)
    t_idx = _tf_idx(timeframe)

    vol_length = _VOL_LENGTH.get(m_idx, _VOL_LENGTH[0])[t_idx]
    mult = _MULT.get(m_idx, _MULT[0])[t_idx]
    rsi_len = _RSI_LENGTH[t_idx]
    vol_thresh = _VOL_THRESHOLD.get(m_idx, 1.0)
    adx_thresh = _ADX_THRESHOLD.get(m_idx, 20.0)
    rsi_buy_thresh = _RSI_BUY_THRESH.get(m_idx, 45.0)

    # ── Indicators ──
    atr_val = compute_atr(df, vol_length)
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    median_tr = tr.rolling(vol_length).mean()
    hybrid_vol = (0.6 * atr_val + 0.4 * float(median_tr.iloc[-1])) if adaptive_vol_smoothing else atr_val
    safe_hybrid_vol = hybrid_vol if hybrid_vol > 0 else float(tr.iloc[-1])

    rsi_series = _rsi(df["close"], rsi_len)
    rsi_value = float(rsi_series.iloc[-1])
    rsi_dist = abs(rsi_value - 50.0)

    # ── Dynamic multiplier ──
    tighten_pct = 0.0
    if tighten_on_momentum:
        if rsi_dist >= 30.0:
            tighten_pct = 0.15
        elif rsi_dist >= 20.0:
            tighten_pct = 0.08
    dynamic_mult = mult * (1.0 - tighten_pct)

    # ── Trailing stop (vectorised init, then iterative for state) ──
    stop_dist = safe_hybrid_vol * dynamic_mult
    n = len(price_src)

    # Warm-up: initialise trail stop at first bar
    trail = np.zeros(n)
    trend_arr = np.zeros(n, dtype=int)
    trail[0] = price_src.iloc[0] - stop_dist
    trend_arr[0] = 1

    for i in range(1, n):
        ps = price_src.iloc[i]
        sd = stop_dist  # uses last calculated stop_dist (could be bar-specific)
        new_stop_up = ps - sd
        new_stop_down = ps + sd

        if trend_arr[i - 1] == 1:
            trail[i] = max(trail[i - 1], new_stop_up)
            if ps < trail[i]:
                trend_arr[i] = -1
                trail[i] = new_stop_down
            else:
                trend_arr[i] = 1
        else:
            trail[i] = min(trail[i - 1], new_stop_down)
            if ps > trail[i]:
                trend_arr[i] = 1
                trail[i] = new_stop_up
            else:
                trend_arr[i] = -1

    current_trend = int(trend_arr[-1])
    prev_trend = int(trend_arr[-2])
    raw_buy = current_trend == 1 and prev_trend == -1
    raw_sell = current_trend == -1 and prev_trend == 1
    raw_signal = raw_buy or raw_sell

    # ── Filters ──
    rsi_buy_ok = rsi_value > rsi_buy_thresh
    rsi_sell_ok = rsi_value < (100.0 - rsi_buy_thresh)
    vol_sma = df["volume"].rolling(20).mean()
    vol_ok = float(df["volume"].iloc[-1]) > float(vol_sma.iloc[-1]) * vol_thresh

    auto_adx = use_adx_filter or (t_idx <= 2 and (m_idx <= 2 or m_idx == 5))
    dmi_plus, dmi_minus, adx_value = _dmi(df, 14)
    adx_ok = adx_value > adx_thresh

    buy_pass = (not use_momentum_filter or rsi_buy_ok) and \
               (not use_volume_filter or vol_ok) and \
               (not auto_adx or adx_ok)
    sell_pass = (not use_momentum_filter or rsi_sell_ok) and \
                (not use_volume_filter or vol_ok) and \
                (not auto_adx or adx_ok)

    confirmed_buy = raw_buy and buy_pass
    confirmed_sell = raw_sell and sell_pass
    confirmed_signal = confirmed_buy or confirmed_sell
    filters_passed = (raw_buy and buy_pass) or (raw_sell and sell_pass)

    if confirmed_buy:
        signal_direction = "long"
    elif confirmed_sell:
        signal_direction = "short"
    else:
        signal_direction = None

    # ── Scoring ──
    if current_trend == 1:
        rsi_score = min(25.0, (rsi_value - rsi_buy_thresh) / (100.0 - rsi_buy_thresh) * 25.0)
    else:
        rsi_score = min(25.0, ((100.0 - rsi_buy_thresh) - rsi_value) / (100.0 - rsi_buy_thresh) * 25.0)

    vol_ratio = float(df["volume"].iloc[-1]) / float(vol_sma.iloc[-1]) if vol_sma.iloc[-1] > 0 else 1.0
    vol_score = min(16.0, max(0.0, (vol_ratio - 1.0) * 16.0))
    adx_score = min(7.5, max(0.0, (adx_value - 15.0) / 30.0 * 7.5))
    composite_score = min(100.0, 50.0 + rsi_score + vol_score + adx_score)

    # ── Features dict for ML / downstream ──
    features = {
        "adaptive_trend": current_trend,
        "adaptive_trailing_stop": round(float(trail[-1]), 6),
        "adaptive_raw_signal": raw_signal,
        "adaptive_confirmed": confirmed_signal,
        "adaptive_score": round(composite_score, 1),
        "adaptive_rsi": round(rsi_value, 1),
        "adaptive_adx": round(adx_value, 1),
        "adaptive_volume_ratio": round(vol_ratio, 3),
        "adaptive_atr": round(atr_val, 6),
        "adaptive_hybrid_vol": round(safe_hybrid_vol, 6),
        "adaptive_dynamic_mult": round(dynamic_mult, 2),
        "adaptive_filters_passed": filters_passed,
        "adaptive_rsi_dist": round(rsi_dist, 1),
        "adaptive_vol_ok": vol_ok,
        "adaptive_adx_ok": adx_ok,
    }

    return AdaptiveTrendResult(
        trend=current_trend,
        trailing_stop=round(float(trail[-1]), 6),
        raw_signal=raw_signal,
        confirmed_signal=confirmed_signal,
        signal_direction=signal_direction,
        composite_score=round(composite_score, 1),
        rsi=round(rsi_value, 1),
        adx=round(adx_value, 1),
        volume_ratio=round(vol_ratio, 3),
        atr=round(atr_val, 6),
        hybrid_vol=round(safe_hybrid_vol, 6),
        dynamic_mult=round(dynamic_mult, 2),
        filters_passed=filters_passed,
        features=features,
    )
