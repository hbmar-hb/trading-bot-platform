"""
Wrapper de indicadores técnicos para uso en estrategias Monte Carlo.
Expone funciones simples que operan sobre DataFrames de pandas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
# INDICADORES BÁSICOS (pandas/numpy nativo)
# ═══════════════════════════════════════════════════════════════

def ema(df: pd.DataFrame, period: int = 20, source: str = "close") -> pd.Series:
    """Exponential Moving Average."""
    return df[source].ewm(span=period, adjust=False).mean()


def sma(df: pd.DataFrame, period: int = 20, source: str = "close") -> pd.Series:
    """Simple Moving Average."""
    return df[source].rolling(period).mean()


def rsi(df: pd.DataFrame, period: int = 14, source: str = "close") -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = df[source].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    return rsi_series


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder)."""
    h, l, c = df["high"], df["low"], df["close"]
    prev_h, prev_l, prev_c = h.shift(1), l.shift(1), c.shift(1)

    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)

    pdm_raw = np.where((h - prev_h) > (prev_l - l), np.maximum(h - prev_h, 0), 0)
    mdm_raw = np.where((prev_l - l) > (h - prev_h), np.maximum(prev_l - l, 0), 0)
    pdm = pd.Series(pdm_raw, index=df.index, dtype=float)
    mdm = pd.Series(mdm_raw, index=df.index, dtype=float)

    alpha = 1.0 / period
    tr_s = tr.ewm(alpha=alpha, adjust=False).mean()
    pdm_s = pdm.ewm(alpha=alpha, adjust=False).mean()
    mdm_s = mdm.ewm(alpha=alpha, adjust=False).mean()

    denom = (pdm_s + mdm_s).replace(0, np.nan)
    dx = 100 * (pdm_s - mdm_s).abs() / denom
    adx_series = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx_series


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3, smooth: int = 3) -> pd.DataFrame:
    """Stochastic Oscillator (%K, %D)."""
    low_min = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    k_raw = 100 * (df["close"] - low_min) / (high_max - low_min)
    k_line = k_raw.rolling(smooth).mean()
    d_line = k_line.rolling(d).mean()
    return pd.DataFrame({"k": k_line, "d": d_line}, index=df.index)


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9, source: str = "close") -> pd.DataFrame:
    """MACD (line, signal, histogram)."""
    ema_fast = df[source].ewm(span=fast, adjust=False).mean()
    ema_slow = df[source].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram}, index=df.index)


def bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0, source: str = "close") -> pd.DataFrame:
    """Bollinger Bands (upper, middle, lower, width_pct, percent_b)."""
    middle = df[source].rolling(period).mean()
    std = df[source].rolling(period).std(ddof=0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    width_pct = ((upper - lower) / middle.replace(0, np.nan)) * 100
    percent_b = (df[source] - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame({
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "width_pct": width_pct,
        "percent_b": percent_b,
    }, index=df.index)


def supertrend(df: pd.DataFrame, period: int = 10, factor: float = 3.0) -> pd.DataFrame:
    """SuperTrend indicator (value, direction: -1=bull, 1=bear)."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    m = len(close)

    # ATR
    tr = np.empty(m)
    tr[0] = high[0] - low[0]
    for i in range(1, m):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    atr_vals = np.full(m, np.nan)
    if m >= period:
        atr_vals[period - 1] = float(np.mean(tr[:period]))
        for i in range(period, m):
            atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr[i]) / period

    val = np.full(m, np.nan)
    dir_ = np.full(m, -1, dtype=int)
    ub = lb = None
    d = -1

    for i in range(m):
        if np.isnan(atr_vals[i]):
            continue
        hl2 = (high[i] + low[i]) / 2
        rUB = hl2 + factor * atr_vals[i]
        rLB = hl2 - factor * atr_vals[i]
        pc = close[i - 1] if i > 0 else close[i]

        ub = rUB if (ub is None or rUB < ub or pc > ub) else ub
        lb = rLB if (lb is None or rLB > lb or pc < lb) else lb

        if d == 1 and close[i] > ub:
            d = -1
        elif d == -1 and close[i] < lb:
            d = 1

        val[i] = lb if d == -1 else ub
        dir_[i] = d

    return pd.DataFrame({"value": val, "direction": dir_}, index=df.index)


# ═══════════════════════════════════════════════════════════════
# INDICADORES AVANZADOS / ICT+SMC
# ═══════════════════════════════════════════════════════════════

def pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.Series:
    """Detecta pivots altos (swing highs)."""
    highs = df["high"]
    pivots = pd.Series(False, index=df.index)
    for i in range(left, len(df) - right):
        if highs.iloc[i] == highs.iloc[i - left:i + right + 1].max():
            pivots.iloc[i] = True
    return pivots


def pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.Series:
    """Detecta pivots bajos (swing lows)."""
    lows = df["low"]
    pivots = pd.Series(False, index=df.index)
    for i in range(left, len(df) - right):
        if lows.iloc[i] == lows.iloc[i - left:i + right + 1].min():
            pivots.iloc[i] = True
    return pivots


def fair_value_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """Detecta Fair Value Gaps (FVG) alcistas y bajistas.
    Retorna DataFrame con columnas: bull_gap (bool), bear_gap (bool), top, bottom.
    """
    n = len(df)
    bull = pd.Series(False, index=df.index)
    bear = pd.Series(False, index=df.index)
    top = pd.Series(np.nan, index=df.index)
    bottom = pd.Series(np.nan, index=df.index)

    for i in range(2, n):
        # Bull FVG: high[i-2] < low[i]
        if df["high"].iloc[i - 2] < df["low"].iloc[i]:
            bull.iloc[i] = True
            top.iloc[i] = df["low"].iloc[i]
            bottom.iloc[i] = df["high"].iloc[i - 2]
        # Bear FVG: low[i-2] > high[i]
        elif df["low"].iloc[i - 2] > df["high"].iloc[i]:
            bear.iloc[i] = True
            top.iloc[i] = df["low"].iloc[i - 2]
            bottom.iloc[i] = df["high"].iloc[i]

    return pd.DataFrame({"bull": bull, "bear": bear, "top": top, "bottom": bottom}, index=df.index)


def volume_profile_poc(df: pd.DataFrame, lookback: int = 50, bins: int = 20) -> float:
    """Price of Control (POC) del volume profile."""
    sub = df.tail(lookback)
    if len(sub) < bins:
        return float(sub["close"].mean())
    prices = sub["close"].values
    volumes = sub["volume"].values
    hist, edges = np.histogram(prices, bins=bins, weights=volumes)
    max_idx = np.argmax(hist)
    poc = (edges[max_idx] + edges[max_idx + 1]) / 2
    return float(poc)


def killzone(df: pd.DataFrame) -> pd.Series:
    """Detecta si la vela cae en una killzone de trading (London/NY)."""
    # Asume que el índice es timestamp
    tz_aware = df.index.tz is not None
    if hasattr(df.index, 'hour'):
        hour = df.index.hour
    else:
        hour = pd.to_datetime(df.index).hour
    # London: 8-17 UTC, NY: 13:30-21 UTC (simplificado a 13-21)
    london = (hour >= 8) & (hour < 17)
    ny = (hour >= 13) & (hour < 21)
    return pd.Series(london | ny, index=df.index)


# ═══════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════

def cross_above(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """True cuando A cruza por encima de B."""
    return (series_a > series_b) & (series_a.shift(1) <= series_b.shift(1))


def cross_below(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """True cuando A cruza por debajo de B."""
    return (series_a < series_b) & (series_a.shift(1) >= series_b.shift(1))


def highest(series: pd.Series, period: int) -> pd.Series:
    """Rolling highest."""
    return series.rolling(period).max()


def lowest(series: pd.Series, period: int) -> pd.Series:
    """Rolling lowest."""
    return series.rolling(period).min()


def range_size(df: pd.DataFrame) -> pd.Series:
    """Tamaño del rango de cada vela (high - low)."""
    return df["high"] - df["low"]


def body_size(df: pd.DataFrame) -> pd.Series:
    """Tamaño del cuerpo de cada vela (abs(close - open))."""
    return (df["close"] - df["open"]).abs()


def is_bullish(df: pd.DataFrame) -> pd.Series:
    """True si la vela es alcista (close > open)."""
    return df["close"] > df["open"]


def is_bearish(df: pd.DataFrame) -> pd.Series:
    """True si la vela es bajista (close < open)."""
    return df["close"] < df["open"]


# ═══════════════════════════════════════════════════════════════
# REGISTRO DE INDICADORES DISPONIBLES
# ═══════════════════════════════════════════════════════════════

AVAILABLE_INDICATORS = {
    "ema": ema,
    "sma": sma,
    "rsi": rsi,
    "atr": atr,
    "adx": adx,
    "stochastic": stochastic,
    "macd": macd,
    "bollinger": bollinger,
    "supertrend": supertrend,
    "pivot_highs": pivot_highs,
    "pivot_lows": pivot_lows,
    "fair_value_gaps": fair_value_gaps,
    "volume_profile_poc": volume_profile_poc,
    "killzone": killzone,
    "cross_above": cross_above,
    "cross_below": cross_below,
    "highest": highest,
    "lowest": lowest,
    "range_size": range_size,
    "body_size": body_size,
    "is_bullish": is_bullish,
    "is_bearish": is_bearish,
}


def get_indicator(name: str):
    """Obtiene una función indicador por nombre."""
    return AVAILABLE_INDICATORS.get(name)


def list_indicators() -> list[dict]:
    """Lista todos los indicadores disponibles con descripción."""
    descriptions = {
        "ema": "Exponential Moving Average",
        "sma": "Simple Moving Average",
        "rsi": "Relative Strength Index (14)",
        "atr": "Average True Range (14)",
        "adx": "Average Directional Index (14)",
        "stochastic": "Stochastic Oscillator (%K, %D)",
        "macd": "MACD (12, 26, 9)",
        "bollinger": "Bollinger Bands (20, 2)",
        "supertrend": "SuperTrend (10, 3.0)",
        "pivot_highs": "Swing Highs (5, 5)",
        "pivot_lows": "Swing Lows (5, 5)",
        "fair_value_gaps": "Fair Value Gaps (FVG)",
        "volume_profile_poc": "Volume Profile POC (50)",
        "killzone": "Killzone detection (London/NY)",
        "cross_above": "Cross Above signal",
        "cross_below": "Cross Below signal",
        "highest": "Rolling Highest",
        "lowest": "Rolling Lowest",
        "range_size": "Candle Range",
        "body_size": "Candle Body Size",
        "is_bullish": "Bullish Candle",
        "is_bearish": "Bearish Candle",
    }
    return [{"name": k, "description": descriptions.get(k, "")} for k in sorted(AVAILABLE_INDICATORS.keys())]
