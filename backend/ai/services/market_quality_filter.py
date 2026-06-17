"""Market Quality Filter — first gate of the pipeline.

Evaluación 2: "Necesitas aprender cuándo NO operar."
This filter blocks scanning in adverse market conditions BEFORE any
signal generation or ML inference happens.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Literal


MarketQuality = Literal["OK", "CHOP", "LOW_LIQUIDITY", "SPREAD_ANOMALY", "API_UNSTABLE"]


@dataclass(frozen=True)
class MarketQualityResult:
    allows_scan: bool
    reason: MarketQuality
    detail: str


class MarketQualityFilter:
    """Decide if market conditions allow scanning for a given symbol."""

    # Thresholds
    _ADX_CHOP_THRESHOLD = 15.0
    _ADX_CHOP_LOOKBACK = 10
    _VOLUME_RATIO_THRESHOLD = 0.20
    _SPREAD_ATR_MULTIPLIER = 3.0
    _ERROR_RATE_THRESHOLD = 0.10

    @classmethod
    def allow_scan(
        cls,
        symbol: str,
        ohlcv: list,
        error_rate_last_hour: float = 0.0,
    ) -> MarketQualityResult:
        """
        Return MarketQualityResult indicating whether scanning should proceed.

        Args:
            symbol: CCXT symbol (e.g. 'BTC/USDT:USDT')
            ohlcv: raw OHLCV list from exchange [[ts, open, high, low, close, volume], ...]
            error_rate_last_hour: fraction of API calls that failed (0.0-1.0)
        """
        if not ohlcv or len(ohlcv) < 30:
            return MarketQualityResult(
                allows_scan=False,
                reason="CHOP",
                detail=f"Insufficient OHLCV data ({len(ohlcv)} candles) for {symbol}",
            )

        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df = df.iloc[-100:]  # Last 100 candles max

        # 1. Chop detection: ADX < 15 during 10+ candles
        adx = cls._calculate_adx(df, period=14)
        if len(adx) >= cls._ADX_CHOP_LOOKBACK:
            recent_adx = adx.iloc[-cls._ADX_CHOP_LOOKBACK:]
            if recent_adx.mean() < cls._ADX_CHOP_THRESHOLD:
                return MarketQualityResult(
                    allows_scan=False,
                    reason="CHOP",
                    detail=f"ADX {recent_adx.mean():.1f} < {cls._ADX_CHOP_THRESHOLD} "
                           f"last {cls._ADX_CHOP_LOOKBACK} candles — ranging/chop",
                )

        # 2. Low liquidity: volume < 20% of recent baseline
        # Use median of last 30 closed candles as baseline (robust to outliers).
        # Use mean of last 3 closed candles as recent volume (smooths single-candle anomalies).
        vol_baseline = df["volume"].iloc[-30:].median()
        recent_vol = df["volume"].iloc[-4:-1].mean()
        if vol_baseline > 0 and (recent_vol / vol_baseline) < cls._VOLUME_RATIO_THRESHOLD:
            return MarketQualityResult(
                allows_scan=False,
                reason="LOW_LIQUIDITY",
                detail=f"Volume {recent_vol/vol_baseline:.1%} of 30-candle median — illiquid",
            )

        # 3. Spread anomaly: spread > 3x ATR
        atr = cls._calculate_atr(df, period=14).iloc[-1]
        last_spread = (df["high"].iloc[-1] - df["low"].iloc[-1])
        if atr > 0 and last_spread > cls._SPREAD_ATR_MULTIPLIER * atr:
            return MarketQualityResult(
                allows_scan=False,
                reason="SPREAD_ANOMALY",
                detail=f"Spread {last_spread:.4f} > {cls._SPREAD_ATR_MULTIPLIER}×ATR {atr:.4f}",
            )

        # 4. Exchange instability
        if error_rate_last_hour > cls._ERROR_RATE_THRESHOLD:
            return MarketQualityResult(
                allows_scan=False,
                reason="API_UNSTABLE",
                detail=f"API error rate {error_rate_last_hour:.1%} > {cls._ERROR_RATE_THRESHOLD:.0%}",
            )

        return MarketQualityResult(
            allows_scan=True,
            reason="OK",
            detail="Market quality checks passed",
        )

    @classmethod
    def _calculate_adx(cls, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Simplified ADX calculation."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)

        plus_dm = plus_dm.where(plus_dm > minus_dm, 0)
        minus_dm = minus_dm.where(minus_dm > plus_dm, 0)

        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr

        dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10) * 100
        adx = dx.ewm(alpha=1 / period, min_periods=period).mean()
        return adx

    @classmethod
    def _calculate_atr(cls, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, min_periods=period).mean()
