"""Market Regime Detector — classifies market state in real-time.

Regimes: TRENDING_BULL / TRENDING_BEAR / RANGING / VOLATILE_SPIKE /
         COMPRESSION / BTC_DOMINANCE / ALT_SEASON

Uses: ADX, ATR percentile, relative volume, BTC/alt correlation,
      funding dynamics, realized volatility.

Hierarchy: L2 Regime — conditions min_score, allowed_tiers, sizing,
           SL/TP profile, leverage_max.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

from loguru import logger

# In-memory cache: (symbol, timeframe) -> (RegimeResult, timestamp)
_cache: dict[tuple[str, str], tuple[Any, datetime]] = {}
_CACHE_TTL_MINUTES = 15


@dataclass(frozen=True)
class RegimeResult:
    regime: str
    adx: float
    atr_percentile: float
    rel_volume: float
    realized_vol: float
    btc_corr: float | None
    funding_accel: float | None
    confidence: float  # 0.0-1.0, how clear is the regime

    def is_trending(self) -> bool:
        return self.regime in ("TRENDING_BULL", "TRENDING_BEAR")

    def is_ranging(self) -> bool:
        return self.regime == "RANGING"

    def is_volatile(self) -> bool:
        return self.regime == "VOLATILE_SPIKE"


# ── Technical indicator helpers ─────────────────────────────────────────────

def _atr(ohlcv: list, period: int = 14) -> list[float]:
    """Return ATR values for each candle."""
    if len(ohlcv) < period + 1:
        return []
    trs = []
    for i in range(1, len(ohlcv)):
        high = float(ohlcv[i][2])
        low = float(ohlcv[i][3])
        prev_close = float(ohlcv[i - 1][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    atrs = []
    for i in range(len(trs)):
        if i < period - 1:
            atrs.append(sum(trs[:i + 1]) / (i + 1))
        elif i == period - 1:
            atrs.append(sum(trs[:period]) / period)
        else:
            atrs.append((atrs[-1] * (period - 1) + trs[i]) / period)
    return atrs


def _adx(ohlcv: list, period: int = 14) -> list[float]:
    """Return ADX values."""
    if len(ohlcv) < period * 2 + 1:
        return []
    plus_dms = []
    minus_dms = []
    trs = []
    for i in range(1, len(ohlcv)):
        high = float(ohlcv[i][2])
        low = float(ohlcv[i][3])
        prev_high = float(ohlcv[i - 1][2])
        prev_low = float(ohlcv[i - 1][3])
        prev_close = float(ohlcv[i - 1][4])

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

        plus_dm = max(high - prev_high, 0) if high - prev_high > prev_low - low else 0
        minus_dm = max(prev_low - low, 0) if prev_low - low > high - prev_high else 0
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)

    # Smooth DM and TR
    smoothed_plus = []
    smoothed_minus = []
    smoothed_tr = []
    for i in range(len(trs)):
        if i < period - 1:
            smoothed_plus.append(sum(plus_dms[:i + 1]) / (i + 1))
            smoothed_minus.append(sum(minus_dms[:i + 1]) / (i + 1))
            smoothed_tr.append(sum(trs[:i + 1]) / (i + 1))
        elif i == period - 1:
            smoothed_plus.append(sum(plus_dms[:period]) / period)
            smoothed_minus.append(sum(minus_dms[:period]) / period)
            smoothed_tr.append(sum(trs[:period]) / period)
        else:
            smoothed_plus.append(smoothed_plus[-1] - smoothed_plus[-1] / period + plus_dms[i])
            smoothed_minus.append(smoothed_minus[-1] - smoothed_minus[-1] / period + minus_dms[i])
            smoothed_tr.append(smoothed_tr[-1] - smoothed_tr[-1] / period + trs[i])

    adxs = []
    for i in range(len(smoothed_tr)):
        if smoothed_tr[i] == 0:
            adxs.append(0.0)
            continue
        di_plus = 100 * smoothed_plus[i] / smoothed_tr[i]
        di_minus = 100 * smoothed_minus[i] / smoothed_tr[i]
        dx = 100 * abs(di_plus - di_minus) / (di_plus + di_minus + 1e-10)
        if i < period - 1:
            adxs.append(sum([dx] * (i + 1)) / (i + 1))
        elif i == period - 1:
            adxs.append(sum([dx] * period) / period)
        else:
            adxs.append((adxs[-1] * (period - 1) + dx) / period)
    return adxs


def _ema(prices: list[float], period: int) -> list[float]:
    """Exponential moving average."""
    if len(prices) < period:
        return []
    k = 2.0 / (period + 1)
    emas = [sum(prices[:period]) / period]
    for p in prices[period:]:
        emas.append(p * k + emas[-1] * (1 - k))
    return emas


def _realized_vol(returns: list[float], annualization_factor: float = 252) -> float:
    """Annualized realized volatility from returns list."""
    if len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    return (variance ** 0.5) * (annualization_factor ** 0.5)


def _percentile(values: list[float], value: float) -> float:
    """Compute percentile of value within values."""
    if not values:
        return 50.0
    sorted_vals = sorted(values)
    below = sum(1 for v in sorted_vals if v < value)
    return (below / len(sorted_vals)) * 100


def _correlation(x: list[float], y: list[float]) -> float:
    """Pearson correlation."""
    n = len(x)
    if n < 2 or n != len(y):
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den_x = sum((xi - mx) ** 2 for xi in x) ** 0.5
    den_y = sum((yi - my) ** 2 for yi in y) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


# ── Main regime detection ───────────────────────────────────────────────────

def detect_regime(symbol: str, timeframe: str, ohlcv: list) -> RegimeResult:
    """Classify market regime from OHLCV data.

    Args:
        symbol: CCXT symbol (e.g. "BTC/USDT:USDT")
        timeframe: e.g. "15m", "1h"
        ohlcv: list of [timestamp, open, high, low, close, volume, ...]

    Returns:
        RegimeResult with regime classification and confidence.
    """
    if len(ohlcv) < 60:
        return RegimeResult(
            regime="RANGING", adx=0, atr_percentile=50,
            rel_volume=1.0, realized_vol=0, btc_corr=None,
            funding_accel=None, confidence=0.0,
        )

    closes = [float(c[4]) for c in ohlcv]
    volumes = [float(c[5]) for c in ohlcv]
    highs = [float(c[2]) for c in ohlcv]
    lows = [float(c[3]) for c in ohlcv]

    # 1. ADX
    adx_values = _adx(ohlcv)
    current_adx = adx_values[-1] if adx_values else 0.0

    # 2. ATR and percentile
    atr_values = _atr(ohlcv)
    current_atr = atr_values[-1] if atr_values else 0.0
    atr_hist = atr_values[-30:] if len(atr_values) >= 30 else atr_values
    atr_p = _percentile(atr_hist, current_atr)

    # 3. Volume relative
    vol_20_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
    rel_volume = volumes[-1] / vol_20_avg if vol_20_avg > 0 else 1.0

    # 4. Realized volatility (annualized)
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    real_vol = _realized_vol(returns[-20:]) if len(returns) >= 20 else 0.0

    # 5. EMA20 for trend direction
    ema20 = _ema(closes, 20)
    above_ema = closes[-1] > ema20[-1] if ema20 else True

    # 6. Recent volatility spike detection (vol > 2σ in last 5 candles)
    recent_returns = returns[-5:] if len(returns) >= 5 else returns
    recent_std = (sum((r - sum(recent_returns) / len(recent_returns)) ** 2 for r in recent_returns) / len(recent_returns)) ** 0.5 if recent_returns else 0
    avg_return = sum(returns[-20:]) / 20 if len(returns) >= 20 else 0
    std_20 = (sum((r - avg_return) ** 2 for r in returns[-20:]) / 20) ** 0.5 if len(returns) >= 20 else 0
    vol_spike = any(abs(r) > avg_return + 2 * std_20 for r in recent_returns) if std_20 > 0 else False

    # 7. Compression detection (range < p10 of last 20 ranges)
    ranges = [highs[i] - lows[i] for i in range(-20, 0)]
    current_range = ranges[-1] if ranges else 0
    range_p = _percentile(ranges, current_range)

    # ── Hierarchical classification ──
    confidence = 0.5

    # 1. Volatile spike
    if atr_p > 90 and vol_spike:
        return RegimeResult(
            "VOLATILE_SPIKE", current_adx, atr_p, rel_volume,
            real_vol, None, None, confidence=0.85,
        )

    # 2. Compression
    if range_p < 10 and atr_p < 20:
        return RegimeResult(
            "COMPRESSION", current_adx, atr_p, rel_volume,
            real_vol, None, None, confidence=0.75,
        )

    # 3. Trending
    if current_adx > 25:
        confidence = min(0.9, 0.6 + (current_adx - 25) / 50)
        if above_ema and rel_volume > 1.0:
            return RegimeResult(
                "TRENDING_BULL", current_adx, atr_p, rel_volume,
                real_vol, None, None, confidence=confidence,
            )
        elif not above_ema and rel_volume > 1.0:
            return RegimeResult(
                "TRENDING_BEAR", current_adx, atr_p, rel_volume,
                real_vol, None, None, confidence=confidence,
            )

    # 4. BTC dominance / Alt season (only for non-BTC alts)
    # These require BTC data; computed separately in _fetch_btc_context
    # For now, return RANGING and let the caller override if BTC context available

    # Default: Ranging
    return RegimeResult(
        "RANGING", current_adx, atr_p, rel_volume,
        real_vol, None, None, confidence=0.5,
    )


def detect_regime_with_btc_context(
    symbol: str, timeframe: str, ohlcv: list,
    btc_ohlcv: list | None = None,
) -> RegimeResult:
    """Detect regime including BTC/alt correlation context."""
    base = detect_regime(symbol, timeframe, ohlcv)

    # Only apply BTC/alt logic for non-BTC symbols
    if "BTC" in symbol.upper() or btc_ohlcv is None or len(btc_ohlcv) < 50:
        return base

    # Compute BTC/alt correlation on returns
    alt_closes = [float(c[4]) for c in ohlcv[-50:]]
    btc_closes = [float(c[4]) for c in btc_ohlcv[-50:]]

    alt_returns = [(alt_closes[i] - alt_closes[i - 1]) / alt_closes[i - 1] for i in range(1, len(alt_closes))]
    btc_returns = [(btc_closes[i] - btc_closes[i - 1]) / btc_closes[i - 1] for i in range(1, len(btc_closes))]

    if len(alt_returns) != len(btc_returns):
        return base

    corr = _correlation(alt_returns, btc_returns)

    # Alt outperformance
    alt_perf = (alt_closes[-1] - alt_closes[0]) / alt_closes[0]
    btc_perf = (btc_closes[-1] - btc_closes[0]) / btc_closes[0]
    alt_outperforms = alt_perf > btc_perf * 1.5

    if corr < 0.3 and alt_outperforms and base.regime in ("RANGING", "TRENDING_BULL"):
        return RegimeResult(
            "ALT_SEASON", base.adx, base.atr_percentile, base.rel_volume,
            base.realized_vol, corr, base.funding_accel, confidence=0.7,
        )

    if corr > 0.8 and btc_perf > alt_perf and base.regime in ("RANGING", "TRENDING_BULL"):
        return RegimeResult(
            "BTC_DOMINANCE", base.adx, base.atr_percentile, base.rel_volume,
            base.realized_vol, corr, base.funding_accel, confidence=0.7,
        )

    return base


# ── Cached wrapper ──────────────────────────────────────────────────────────

def get_regime(symbol: str, timeframe: str, ohlcv: list) -> RegimeResult:
    """Cached regime detection with 15-minute TTL."""
    key = (symbol.upper(), timeframe)
    now = datetime.now(timezone.utc)
    cached = _cache.get(key)
    if cached:
        result, ts = cached
        if now - ts < timedelta(minutes=_CACHE_TTL_MINUTES):
            return result

    result = detect_regime_with_btc_context(symbol, timeframe, ohlcv)
    _cache[key] = (result, now)
    return result


def regime_gate_for_signal(symbol: str, direction: str, regime: RegimeResult) -> dict:
    """Return trading adjustments based on regime.

    Returns dict with:
        min_score_adjust: int (add to base min_score)
        allowed_tiers: list[str] | None (override, None = no change)
        sizing_multiplier: float (1.0 = no change)
        leverage_max: float | None (override max leverage)
        blocked: bool
        reason: str | None
    """
    r = regime.regime

    if r == "VOLATILE_SPIKE":
        return {
            "blocked": False,
            "min_score_adjust": 15,
            "allowed_tiers": None,  # respect bot config (MODERATE/WEAK now active)
            "sizing_multiplier": 0.3,
            "leverage_max": 0.5,  # 50% of base leverage
            "reason": "volatile_spike: sizing 30%, score +15",
        }

    if r == "COMPRESSION":
        return {
            "blocked": False,
            "min_score_adjust": 10,
            "allowed_tiers": None,
            "sizing_multiplier": 0.5,
            "leverage_max": None,
            "reason": "compression: sizing 50%, score +10",
        }

    if r == "RANGING":
        return {
            "blocked": False,
            "min_score_adjust": 10,
            "allowed_tiers": None,  # respect bot config (MODERATE/WEAK now active)
            "sizing_multiplier": 0.5,
            "leverage_max": None,
            "reason": "ranging: sizing 50%, score +10",
        }

    if r in ("TRENDING_BULL", "TRENDING_BEAR"):
        return {
            "blocked": False,
            "min_score_adjust": 0,
            "allowed_tiers": None,
            "sizing_multiplier": 1.0,
            "leverage_max": None,
            "reason": f"trending: normal sizing",
        }

    if r == "ALT_SEASON":
        return {
            "blocked": False,
            "min_score_adjust": 0,
            "allowed_tiers": None,
            "sizing_multiplier": 0.8,
            "leverage_max": None,
            "reason": "alt_season: sizing 80%",
        }

    if r == "BTC_DOMINANCE":
        return {
            "blocked": False,
            "min_score_adjust": 5,
            "allowed_tiers": None,
            "sizing_multiplier": 0.9,
            "leverage_max": None,
            "reason": "btc_dominance: score +5, sizing 90%",
        }

    # Fallback
    return {
        "blocked": False,
        "min_score_adjust": 0,
        "allowed_tiers": None,
        "sizing_multiplier": 1.0,
        "leverage_max": None,
        "reason": None,
    }
