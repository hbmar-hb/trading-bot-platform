"""
Open Interest / CVD Rate of Change tracker.

Usa CCXT fetch_open_interest para obtener OI histórico.
CVD se aproxima mediante delta de volumen si está disponible.

Reglas de filtro:
- OI ROC > +15% + precio sube → squeeze potencial → caution
- OI ROC < -10% + precio baja → falta convicción → caution
- OI sube + precio baja → longs acumulando → bullish long / bearish short
- OI baja + precio sube → shorts cubriendo → bearish long / bullish short
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.exchanges.base import BaseExchange

# ── Constantes ──────────────────────────────────────────────
OI_ROC_CAUTION_PCT = 15.0
OI_ROC_BLOCK_PCT = 25.0
CVD_ROC_CAUTION_PCT = 20.0
CACHE_TTL_SECONDS = 300  # 5 minutos


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _roc(values: list[float]) -> float | None:
    """Rate of change %: (last - first) / |first| * 100"""
    if not values or len(values) < 2 or values[0] == 0:
        return None
    return (values[-1] - values[0]) / abs(values[0]) * 100.0


async def fetch_oi_history(
    exchange: "BaseExchange",
    symbol: str,
    timeframe: str = "1h",
    limit: int = 24,
) -> list[float]:
    """Devuelve serie de Open Interest (en contratos/USDT)."""
    try:
        if not hasattr(exchange._client, "fetch_open_interest_history"):
            return []
        oi_data = await exchange._client.fetch_open_interest_history(
            symbol, timeframe=timeframe, limit=limit, params={}
        )
        if not oi_data:
            return []
        # CCXT devuelve [{timestamp, openInterestValue, ...}, ...]
        return [float(d.get("openInterestValue", d.get("oi", 0))) for d in oi_data if d]
    except Exception:
        return []


async def fetch_cvd_proxy(
    exchange: "BaseExchange",
    symbol: str,
    limit: int = 100,
) -> list[float]:
    """
    Aproxima CVD usando trades públicos (buy vs sell volume).
    Devuelve serie acumulada de CVD.
    """
    try:
        if not hasattr(exchange._client, "fetch_trades"):
            return []
        trades = await exchange._client.fetch_trades(symbol, limit=limit)
        if not trades:
            return []
        cvd = 0.0
        series = []
        for t in trades:
            side = t.get("side", "")
            amount = float(t.get("amount", 0))
            price = float(t.get("price", 0))
            vol = amount * price
            if side == "buy":
                cvd += vol
            elif side == "sell":
                cvd -= vol
            series.append(cvd)
        return series
    except Exception:
        return []


def oi_cvd_gate(
    oi_roc: float | None,
    cvd_roc: float | None,
    price_roc: float | None,
    direction: str,
) -> dict:
    """
    Devuelve dict con blocked, caution, reason basado en OI/CVD.
    """
    blocked = False
    caution = False
    reasons = []

    if oi_roc is not None:
        if abs(oi_roc) >= OI_ROC_BLOCK_PCT:
            blocked = True
            reasons.append(f"OI ROC {oi_roc:+.1f}% >= {OI_ROC_BLOCK_PCT}%")
        elif abs(oi_roc) >= OI_ROC_CAUTION_PCT:
            caution = True
            reasons.append(f"OI ROC {oi_roc:+.1f}% >= {OI_ROC_CAUTION_PCT}%")

        # Divergencia OI vs precio
        if price_roc is not None:
            if oi_roc > 10 and price_roc < -2:
                # Longs acumulando en caída
                if direction == "long":
                    caution = True
                    reasons.append("OI↑ + price↓ (longs accumulating)")
                else:
                    blocked = True
                    reasons.append("OI↑ + price↓ (short squeeze risk)")
            elif oi_roc < -10 and price_roc > 2:
                # Shorts cubriendo en subida
                if direction == "short":
                    caution = True
                    reasons.append("OI↓ + price↑ (shorts covering)")
                else:
                    blocked = True
                    reasons.append("OI↓ + price↑ (weak rally)")

    if cvd_roc is not None and abs(cvd_roc) >= CVD_ROC_CAUTION_PCT:
        if direction == "long" and cvd_roc < 0:
            caution = True
            reasons.append(f"CVD ROC {cvd_roc:+.1f}% negative (selling pressure)")
        elif direction == "short" and cvd_roc > 0:
            caution = True
            reasons.append(f"CVD ROC {cvd_roc:+.1f}% positive (buying pressure)")

    return {
        "blocked": blocked,
        "caution": caution,
        "reason": "; ".join(reasons) if reasons else None,
        "oi_roc": round(oi_roc, 2) if oi_roc is not None else None,
        "cvd_roc": round(cvd_roc, 2) if cvd_roc is not None else None,
        "price_roc": round(price_roc, 2) if price_roc is not None else None,
    }


async def evaluate_oi_cvd(
    exchange: "BaseExchange",
    symbol: str,
    direction: str,
) -> dict:
    """
    Evaluación completa: obtiene OI, CVD, precio, calcula ROCs y aplica gate.
    """
    oi_series = await fetch_oi_history(exchange, symbol)
    cvd_series = await fetch_cvd_proxy(exchange, symbol)

    # Precio para calcular divergencia
    price_series = []
    try:
        if hasattr(exchange._client, "fetch_ohlcv"):
            ohlcv = await exchange._client.fetch_ohlcv(symbol, timeframe="1h", limit=24)
            if ohlcv:
                price_series = [float(c[4]) for c in ohlcv]  # close prices
    except Exception:
        pass

    oi_roc = _roc(oi_series)
    cvd_roc = _roc(cvd_series)
    price_roc = _roc(price_series)

    return oi_cvd_gate(oi_roc, cvd_roc, price_roc, direction)
