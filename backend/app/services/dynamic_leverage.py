"""
Apalancamiento Dinámico — ajusta leverage en tiempo real según:
  1. ATR spike (> 2× media histórica) → reduce 50%
  2. Funding rate extremo (> 0.05%) → reduce 50%
  3. Evento macro próximo (< 30 min) → max 3×

Input: base_leverage, symbol, ohlcv_history, funding_rate, macro_context
Output: leverage ajustado (int >= 1)
"""
from __future__ import annotations

import statistics
from decimal import Decimal
from typing import Any

from loguru import logger


def compute_dynamic_leverage(
    base_leverage: int,
    current_atr: float,
    atr_history: list[float],
    funding_rate: float | None = None,
    macro_blocked: bool = False,
    macro_caution: bool = False,
) -> int:
    """
    Calcula leverage dinámico basado en condiciones de mercado.

    Args:
        base_leverage: leverage configurado por el usuario en el bot
        current_atr: ATR actual del timeframe de operación
        atr_history: lista de valores ATR históricos (ej: últimas 200 velas)
        funding_rate: funding rate actual del exchange (%), ej: 0.01 = 0.01%
        macro_blocked: True si macro_gate_for_signal bloquea
        macro_caution: True si macro_gate_for_signal advierte

    Returns:
        Leverage ajustado (int >= 1)
    """
    leverage = base_leverage
    reasons: list[str] = []

    # 1. ATR spike
    if atr_history:
        # Filtrar ceros y valores inválidos
        valid_atrs = [a for a in atr_history if a > 0]
        if len(valid_atrs) >= 20:
            atr_mean = statistics.mean(valid_atrs)
            if atr_mean > 0 and current_atr > 2.0 * atr_mean:
                leverage = max(1, int(leverage * 0.5))
                reasons.append(
                    f"ATR spike: {current_atr:.4f} vs media {atr_mean:.4f} "
                    f"({current_atr/atr_mean:.1f}×)"
                )

    # 2. Funding rate extremo
    if funding_rate is not None and abs(funding_rate) > 0.05:
        leverage = max(1, int(leverage * 0.5))
        reasons.append(f"Funding rate extremo: {funding_rate:.4f}%")

    # 3. Macro event próximo
    if macro_blocked:
        leverage = 1
        reasons.append("Evento macro bloqueado — leverage mínimo")
    elif macro_caution:
        leverage = min(leverage, 3)
        reasons.append("Evento macro cercano — leverage cap 3×")

    final = max(1, leverage)
    if final != base_leverage:
        logger.info(
            f"[DynamicLeverage] {base_leverage}x → {final}x | "
            f"reasons: {', '.join(reasons)}"
        )
    return final


def extract_atr_history(ohlcv: list[dict], atr_len: int = 14) -> list[float]:
    """
    Calcula ATR rolling sobre una lista de velas OHLCV y devuelve
    la serie completa de valores ATR (sin los primeros `atr_len` NaN).
    """
    import pandas as pd

    if len(ohlcv) < atr_len + 1:
        return []

    df = pd.DataFrame(ohlcv)[["high", "low", "close"]].astype(float)
    h = df["high"]
    l = df["low"]
    prev_c = df["close"].shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_len).mean()
    valid = atr.dropna().tolist()
    return [float(v) for v in valid]


async def fetch_funding_rate(symbol: str, exchange: Any) -> float | None:
    """
    Intenta obtener el funding rate actual del exchange.
    Devuelve None si no está disponible o falla.
    """
    try:
        # CCXT method: fetchFundingRate
        if hasattr(exchange, "fetchFundingRate"):
            rate_data = await exchange.fetchFundingRate(symbol)
            if rate_data and "fundingRate" in rate_data:
                return float(rate_data["fundingRate"]) * 100  # convert to %
    except Exception as exc:
        logger.debug(f"[DynamicLeverage] fetch_funding_rate failed: {exc}")
    return None
