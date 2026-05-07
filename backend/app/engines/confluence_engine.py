"""Confluence engine — combines ICT + SMC into a scored trading setup.

Scoring breakdown (max ~100 pts):
  Structure break type  : CHoCH +20 | BOS +12
  Entry trigger         : OB +15    | FVG +10
  Aligned FVGs          : up to +12
  Liquidity sweep       : +18
  Premium/Discount      : +10
  Killzone (UTC)        : +10
  EQ obstacle penalty   : -8

Confidence thresholds: HIGH ≥75, MEDIUM ≥55, LOW <55.

No ML model yet — the system logs every signal with its full feature set.
The anti-fake XGBoost layer will activate automatically once
≥200 labeled outcomes are available (tracked by OutcomeTracker).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app.core.ict_engine import ICTResult, analyze as ict_analyze
from app.engines.smc_engine import SMCContext, analyze_smc, compute_atr, compute_adx

_ADX_TREND_THRESHOLD = 25.0  # below this → ranging market


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ConfluenceResult:
    direction:  str    # 'long' | 'short'
    score:      float  # 0-100
    confidence: str    # 'HIGH' | 'MEDIUM' | 'LOW'

    entry_price:  float
    entry_zone:   tuple[float, float]
    stop_loss:    float
    take_profit_1: float
    take_profit_2: float
    risk_reward:  float  # TP1 R:R

    components: dict = field(default_factory=dict)
    features:   dict = field(default_factory=dict)
    warnings:   list = field(default_factory=list)
    explanation: str = ""

    ict: ICTResult = field(repr=False, default=None)
    smc: SMCContext = field(repr=False, default=None)


# ── Public API ─────────────────────────────────────────────────────────────────

def analyze_confluence(
    candles:    list[dict],
    ticker:     str,
    timeframe:  str,
    pivot_len:  int   = 5,
    atr_mult:   float = 0.3,
    atr_len:    int   = 14,
    entry_mode: str   = "ob_or_fvg",
) -> Optional[ConfluenceResult]:
    """
    Run ICT + SMC analysis and return a scored ConfluenceResult.
    Returns None when the ICT engine finds no actionable signal.
    candles must be CLOSED candles only (exclude the current forming bar).
    """
    ict = ict_analyze(candles, pivot_len, atr_mult, atr_len, entry_mode)

    if ict.signal == "none" or ict.entry_zone is None:
        return None

    smc = analyze_smc(candles, ict)

    df        = pd.DataFrame(candles)[["open", "high", "low", "close", "volume"]].astype(float)
    atr_val   = compute_atr(df, atr_len)
    adx_val   = compute_adx(df, atr_len)
    is_long   = ict.signal == "long"
    direction = ict.signal
    ranging   = adx_val < _ADX_TREND_THRESHOLD  # True → reduce timing/sweep weights

    score      = 0.0
    components: dict = {}
    warnings:   list = []

    # ── 1. Structure break type ───────────────────────────────────────────────
    if ict.last_break:
        if ict.last_break.kind == "CHoCH":
            score += 20
            components["structure"] = "CHoCH — cambio de sesgo confirmado"
        else:
            score += 12
            components["structure"] = "BOS — continuación de tendencia"

    # ── 2. Entry trigger ──────────────────────────────────────────────────────
    if ict.trigger == "ob" and ict.active_ob:
        score += 15
        ob = ict.active_ob
        components["trigger"] = f"Order Block activo {ob.bottom:.4f}–{ob.top:.4f}"
    elif ict.trigger == "fvg":
        score += 10
        components["trigger"] = "Fair Value Gap activo"

    # ── 3. Aligned background FVGs ───────────────────────────────────────────
    if smc.fvg_aligned_count > 0:
        bonus = min(smc.fvg_aligned_count * 4, 12)
        score += bonus
        components["fvg_context"] = (
            f"{smc.fvg_aligned_count} FVG{'s' if smc.fvg_aligned_count > 1 else ''} "
            f"sin llenar alineado{'s' if smc.fvg_aligned_count > 1 else ''}"
        )

    # ── 4. Liquidity sweep (strongest confluence) ─────────────────────────────
    sweep_pts = 10 if ranging else 18  # reduced weight in ranging markets
    if smc.liquidity_sweep:
        score += sweep_pts
        label = "Buy-Side (BSL)" if smc.liquidity_sweep == "BSL" else "Sell-Side (SSL)"
        components["sweep"] = f"Sweep de liquidez {label} en {smc.sweep_level:.4f}"
    else:
        warn = "Sin sweep de liquidez previo — confluencia reducida"
        if ranging:
            warn += f" (rango, ADX {adx_val:.0f})"
        warnings.append(warn)

    # ── 5. Premium / Discount alignment ──────────────────────────────────────
    if is_long and smc.pd_position < 0.5:
        score += 10
        components["pd_array"] = f"Precio en zona discount ({smc.pd_position:.2f})"
    elif not is_long and smc.pd_position > 0.5:
        score += 10
        components["pd_array"] = f"Precio en zona premium ({smc.pd_position:.2f})"
    else:
        zone = "premium" if is_long else "discount"
        warnings.append(f"Precio en zona {zone} — condición desfavorable para {direction}")

    # ── 6. Killzone ───────────────────────────────────────────────────────────
    hour_utc  = datetime.now(timezone.utc).hour
    kz        = _killzone(hour_utc)
    kz_pts    = 5 if ranging else 10   # reduced weight in ranging markets
    if kz:
        score += kz_pts
        components["killzone"] = f"Killzone {kz} activa ({hour_utc:02d}h UTC)"
    else:
        kz_warn = f"Fuera de killzone óptima (hora UTC: {hour_utc:02d}h)"
        if ranging:
            kz_warn += f" — mercado en rango (ADX {adx_val:.0f}), peso reducido"
        warnings.append(kz_warn)

    # ── 7. EQ obstacle penalty ────────────────────────────────────────────────
    entry_mid = (ict.entry_zone[0] + ict.entry_zone[1]) / 2
    if is_long and ict.eq_highs:
        nearest = min(ict.eq_highs)
        if nearest < entry_mid * 1.01:  # EQ High within 1% above entry
            score -= 8
            warnings.append(f"EQ High en {nearest:.4f} actúa como techo cercano")
    elif not is_long and ict.eq_lows:
        nearest = max(ict.eq_lows)
        if nearest > entry_mid * 0.99:
            score -= 8
            warnings.append(f"EQ Low en {nearest:.4f} actúa como suelo cercano")

    score = max(0.0, min(100.0, score))

    if score >= 75:
        confidence = "HIGH"
    elif score >= 55:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # ── Levels ────────────────────────────────────────────────────────────────
    ez  = ict.entry_zone
    mid = (ez[0] + ez[1]) / 2

    if is_long:
        sl   = max(ict.eq_lows)  if ict.eq_lows  else ez[0] - atr_val * 2.0
        risk = mid - sl
        tp1  = mid + risk * 1.5
        tp2  = mid + risk * 2.5
    else:
        sl   = min(ict.eq_highs) if ict.eq_highs else ez[1] + atr_val * 2.0
        risk = sl - mid
        tp1  = mid - risk * 1.5
        tp2  = mid - risk * 2.5

    rr = (tp1 - mid) / risk if risk > 0 else 0.0
    if not is_long:
        rr = (mid - tp1) / risk if risk > 0 else 0.0

    # ── Features for future ML training ──────────────────────────────────────
    last = df.iloc[-1]
    vol_avg = float(df["volume"].iloc[-20:].mean()) if len(df) >= 20 else float(df["volume"].mean())

    features = {
        "break_type":        ict.last_break.kind if ict.last_break else None,
        "trigger":           ict.trigger,
        "bias":              ict.bias,
        "fvg_aligned_count": smc.fvg_aligned_count,
        "ob_distance_atr":   round(smc.ob_distance_atr, 3) if smc.ob_distance_atr else None,
        "sweep_detected":    smc.liquidity_sweep is not None,
        "sweep_type":        smc.liquidity_sweep,
        "pd_position":       round(smc.pd_position, 3),
        "killzone":          kz,
        "hour_utc":          hour_utc,
        "day_of_week":       datetime.now(timezone.utc).weekday(),
        "eq_highs_count":    len(ict.eq_highs),
        "eq_lows_count":     len(ict.eq_lows),
        "volume_ratio":      round(float(last["volume"]) / vol_avg, 3) if vol_avg > 0 else 1.0,
        "spread_atr":        round(float(last["high"] - last["low"]) / atr_val, 3) if atr_val > 0 else 0.0,
        "adx":               round(adx_val, 1),
        "market_regime":     "ranging" if ranging else "trending",
        "score":             round(score, 1),
    }

    explanation = _build_explanation(direction, score, components)

    return ConfluenceResult(
        direction     = direction,
        score         = round(score, 1),
        confidence    = confidence,
        entry_price   = round(mid, 6),
        entry_zone    = (ez[0], ez[1]),
        stop_loss     = round(sl, 6),
        take_profit_1 = round(tp1, 6),
        take_profit_2 = round(tp2, 6),
        risk_reward   = round(rr, 2),
        components    = components,
        features      = features,
        warnings      = warnings,
        explanation   = explanation,
        ict           = ict,
        smc           = smc,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _killzone(hour: int) -> Optional[str]:
    if 2 <= hour <= 5:
        return "Asian"
    if 7 <= hour <= 10:
        return "London"
    if 13 <= hour <= 16:
        return "NY"
    return None


def _build_explanation(direction: str, score: float, components: dict) -> str:
    label = "LONG" if direction == "long" else "SHORT"
    lines = [f"Setup {label} — confluencia {score:.0f}/100"]
    for v in components.values():
        lines.append(f"• {v}")
    return "\n".join(lines)
