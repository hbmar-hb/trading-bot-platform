"""
Horizonte Temporal Dinámico — TP/SL ajustados por ATR + volatilidad.

Reglas:
- ATR > p80 → SL/TP ×1.5 (evita stop-outs por ruido)
- ATR < p20 → SL/TP ×0.7 (aprovecha rangos ajustados)
- RANGING/COMPRESSION → reduce 10% adicional
- VOLATILE_SPIKE → aumenta 20% adicional
- Nunca permite SL más ancho que 3× el SL original
- Nunca permite SL más estrecho que 0.5× el SL original
"""
from __future__ import annotations

from decimal import Decimal


def compute_dynamic_tp_sl(
    entry_price: float,
    direction: str,
    atr_value: float,
    atr_percentile: float,
    base_sl: float,
    base_tp1: float,
    base_tp2: float,
    regime: str = "RANGING",
) -> tuple[float, float, float, dict]:
    """
    Devuelve (adjusted_sl, adjusted_tp1, adjusted_tp2, metadata).
    """
    if entry_price <= 0 or atr_value <= 0:
        return base_sl, base_tp1, base_tp2, {"applied": False, "reason": "invalid_inputs"}

    # Factor base por ATR percentile
    if atr_percentile >= 80:
        multiplier = 1.5
    elif atr_percentile >= 60:
        multiplier = 1.2
    elif atr_percentile <= 20:
        multiplier = 0.7
    elif atr_percentile <= 40:
        multiplier = 0.85
    else:
        multiplier = 1.0

    # Ajuste por régimen
    regime_adj = 1.0
    if regime in ("RANGING", "COMPRESSION"):
        regime_adj = 0.9
    elif regime == "VOLATILE_SPIKE":
        regime_adj = 1.2

    final_mult = multiplier * regime_adj

    # Clamp entre 0.5× y 3×
    final_mult = max(0.5, min(3.0, final_mult))

    entry = entry_price

    # Calcular distancias base
    sl_dist = abs(entry - base_sl)
    tp1_dist = abs(base_tp1 - entry)
    tp2_dist = abs(base_tp2 - entry)

    # Aplicar multiplicador
    new_sl_dist = sl_dist * final_mult
    new_tp1_dist = tp1_dist * final_mult
    new_tp2_dist = tp2_dist * final_mult

    if direction == "long":
        adj_sl = entry - new_sl_dist
        adj_tp1 = entry + new_tp1_dist
        adj_tp2 = entry + new_tp2_dist
    else:
        adj_sl = entry + new_sl_dist
        adj_tp1 = entry - new_tp1_dist
        adj_tp2 = entry - new_tp2_dist

    metadata = {
        "applied": True,
        "atr_percentile": atr_percentile,
        "atr_multiplier": round(multiplier, 2),
        "regime": regime,
        "regime_adj": round(regime_adj, 2),
        "final_multiplier": round(final_mult, 2),
        "original_sl": round(base_sl, 4),
        "adjusted_sl": round(adj_sl, 4),
        "original_tp1": round(base_tp1, 4),
        "adjusted_tp1": round(adj_tp1, 4),
        "original_tp2": round(base_tp2, 4),
        "adjusted_tp2": round(adj_tp2, 4),
    }

    return adj_sl, adj_tp1, adj_tp2, metadata
