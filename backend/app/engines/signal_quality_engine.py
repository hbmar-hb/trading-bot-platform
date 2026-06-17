"""Signal quality assessment — Fase 1.5 (heuristic anti-fake layer).

Runs after confluence analysis using the already-computed ConfluenceResult
features.  No ML model required.

Scoring (max ~105, capped at 100), blended 35% heuristic + 65% confluence:
  Volume > 1.5×           +15
  Spread < 1×ATR          +15
  Liquidity sweep         +20
  FVGs aligned (2+/1)     +15/+8
  Killzone active         +15
  P/D position deep       +15
  Entry trigger (OB/FVG)  +10/+5

Red flags (each blocks / cautions):
  Volume < 0.5×           → CAUTION
  Spread > 2×ATR          → CAUTION
  2+ red flags            → BLOCK → AVOID

Execution penalty: if spread >2×ATR OR volume <0.5×, subtract 15 from blended
Quality tiers: STRONG ≥70 | MODERATE ≥50 | WEAK <50
Anti-fake:     BLOCK (2+ flags) | CAUTION (1 flag) | CLEAR (0 flags)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.engines.confluence_engine import ConfluenceResult


@dataclass
class QualityAssessment:
    quality_score:    float
    quality_tier:     str        # WEAK | MODERATE | STRONG
    anti_fake_status: str        # CLEAR | CAUTION | BLOCK
    recommendation:   str        # ENTER | WAIT | AVOID
    success_probability: float | None = None  # XGBoost success probability (0-1)
    red_flags:        list[str]  = field(default_factory=list)
    green_flags:      list[str]  = field(default_factory=list)


def assess_quality(result: ConfluenceResult) -> QualityAssessment:
    """Evaluate signal quality from an existing ConfluenceResult.

    Blends heuristic score (timing/volume/spread) with confluence score
    (structural ICT/SMC strength) so that tier reflects *both* dimensions.
    """
    f                = result.features
    direction        = result.direction
    confluence_score = getattr(result, "score", 0.0)

    green_flags: list[str] = []
    red_flags:   list[str] = []
    heuristic = 0.0

    # ── Volume confirmation ───────────────────────────────────────────────────
    vol_ratio = f.get("volume_ratio", 1.0)
    if vol_ratio > 1.5:
        heuristic += 15
        green_flags.append(f"Volumen {vol_ratio:.1f}× sobre media — confirmación fuerte")
    elif vol_ratio > 1.0:
        heuristic += 7
        green_flags.append(f"Volumen {vol_ratio:.1f}× sobre media")
    elif vol_ratio < 0.5:
        red_flags.append(f"Volumen {vol_ratio:.1f}× — falta de interés del mercado")

    # ── Spread / candle quality ───────────────────────────────────────────────
    spread_atr = f.get("spread_atr", 0.0)
    if spread_atr < 1.0:
        heuristic += 15
        green_flags.append("Estructura de vela limpia (spread < 1×ATR)")
    elif spread_atr < 1.5:
        heuristic += 7
    elif spread_atr > 2.0:
        red_flags.append(f"Spread {spread_atr:.1f}×ATR — posible spike / manipulación")

    # ── Liquidity sweep ───────────────────────────────────────────────────────
    if f.get("sweep_detected"):
        heuristic += 20
        sweep_type = f.get("sweep_type") or ""
        green_flags.append(
            f"Liquidity sweep {'BSL' if sweep_type == 'BSL' else 'SSL'} confirmado"
        )

    # ── Aligned FVGs ─────────────────────────────────────────────────────────
    fvg_n = f.get("fvg_aligned_count", 0)
    if fvg_n >= 2:
        heuristic += 15
        green_flags.append(f"{fvg_n} FVGs alineados sin llenar")
    elif fvg_n == 1:
        heuristic += 8
        green_flags.append("FVG alineado sin llenar")

    # ── Killzone ──────────────────────────────────────────────────────────────
    kz = f.get("killzone")
    if kz:
        heuristic += 15
        green_flags.append(f"Killzone {kz} activa — timing óptimo")

    # ── Premium / Discount position — directional guard ───────────────────────
    pd_pos = f.get("pd_position", 0.5)
    if direction == "long":
        if pd_pos > 0.75:
            heuristic -= 30
            red_flags.append(f"LONG en premium profundo ({pd_pos:.0%}) — contratendencia")
        elif pd_pos > 0.60:
            heuristic -= 15
            red_flags.append(f"LONG en premium ({pd_pos:.0%}) — riesgo de reversal")
        elif pd_pos < 0.35:
            heuristic += 15
            green_flags.append(f"Zona discount profunda ({pd_pos:.0%})")
        elif pd_pos < 0.5:
            heuristic += 8
            green_flags.append(f"Zona discount ({pd_pos:.0%})")
    else:  # short
        if pd_pos < 0.25:
            heuristic -= 30
            red_flags.append(f"SHORT en discount profundo ({pd_pos:.0%}) — contratendencia")
        elif pd_pos < 0.40:
            heuristic -= 15
            red_flags.append(f"SHORT en discount ({pd_pos:.0%}) — riesgo de reversal")
        elif pd_pos > 0.65:
            heuristic += 15
            green_flags.append(f"Zona premium alta ({pd_pos:.0%})")
        elif pd_pos > 0.5:
            heuristic += 8
            green_flags.append(f"Zona premium ({pd_pos:.0%})")

    # ── Entry trigger quality ─────────────────────────────────────────────────
    trigger = f.get("trigger")
    if trigger == "ob":
        heuristic += 10
        green_flags.append("Order Block como trigger preciso")
    elif trigger == "fvg":
        heuristic += 5
        green_flags.append("FVG como trigger")

    # ── Ensemble confirmation: RSI + Stochastic + Volume Profile ──────────────
    rsi = f.get("rsi", 50.0)
    stoch_k = f.get("stoch_k", 50.0)
    poc = f.get("poc")
    entry_price = getattr(result, "entry_price", 0)

    if direction == "long":
        if rsi < 30:
            heuristic += 5
            green_flags.append(f"RSI sobrevendido ({rsi:.1f}) — confirma LONG")
        elif rsi > 70:
            heuristic -= 5
            red_flags.append(f"RSI sobrecomprado ({rsi:.1f}) — precaución LONG")
        if stoch_k < 20:
            heuristic += 3
            green_flags.append(f"Stochastic sobrevendido ({stoch_k:.1f}) — confirma LONG")
        elif stoch_k > 80:
            heuristic -= 3
            red_flags.append(f"Stochastic sobrecomprado ({stoch_k:.1f}) — precaución LONG")
    else:  # short
        if rsi > 70:
            heuristic += 5
            green_flags.append(f"RSI sobrecomprado ({rsi:.1f}) — confirma SHORT")
        elif rsi < 30:
            heuristic -= 5
            red_flags.append(f"RSI sobrevendido ({rsi:.1f}) — precaución SHORT")
        if stoch_k > 80:
            heuristic += 3
            green_flags.append(f"Stochastic sobrecomprado ({stoch_k:.1f}) — confirma SHORT")
        elif stoch_k < 20:
            heuristic -= 3
            red_flags.append(f"Stochastic sobrevendido ({stoch_k:.1f}) — precaución SHORT")

    if poc and entry_price and abs(entry_price - poc) / max(poc, 1e-10) < 0.01:
        heuristic += 2
        green_flags.append("Precio cerca del POC — zona de máximo volumen")

    # ── Monte Carlo Setup Base quality adjustments ─────────────────────────
    mc_passed = f.get("mc_setup_score") is not None
    if mc_passed:
        mc_score = f.get("mc_setup_score", 0)
        mc_bias = f.get("mc_direction_bias")
        mc_conf = f.get("mc_direction_confidence", 0)
        mc_tier = f.get("mc_confidence_tier", "low")

        # If MC validation failed → force caution
        if mc_score is not None and mc_score < 50:
            red_flags.append(f"MC validation weak (score={mc_score}) — setup no robusto")

        # Directional alignment boost/penalty
        if mc_bias and mc_bias != "neutral":
            if mc_bias == direction and mc_conf > 0.7:
                heuristic += 10
                green_flags.append(f"MC Setup dirección alineada ({mc_bias}, conf={mc_conf:.2f})")
            elif mc_bias != direction and mc_conf > 0.6:
                heuristic -= 10
                red_flags.append(f"MC Setup dirección contradice ({mc_bias} vs {direction})")

    heuristic = round(min(100.0, max(0.0, heuristic)), 1)
    # Blend: 35% heuristic (timing/volume/spread) + 65% confluence (price structure)
    # Confluence score captures structural edge (ICT/SMC) which correlates better
    # with realized PnL than timing heuristics alone.
    blended = round(0.35 * heuristic + 0.65 * confluence_score, 1)

    # Execution penalty: poor execution conditions downgrade the tier
    exec_red_flags = [
        f for f in red_flags
        if "falta de interés" in f or "spike / manipulación" in f
    ]
    if exec_red_flags:
        blended = max(0.0, blended - 15.0)

    if blended >= 70:
        quality_tier = "STRONG"
    elif blended >= 50:
        quality_tier = "MODERATE"
    else:
        quality_tier = "WEAK"

    if len(red_flags) >= 2:
        anti_fake_status = "BLOCK"
        recommendation   = "AVOID"
    elif len(red_flags) == 1:
        anti_fake_status = "CAUTION"
        recommendation   = "WAIT"
    else:
        anti_fake_status = "CLEAR"
        # Datos reales muestran que MODERATE CLEAR es rentable (+1.2% avg)
        recommendation   = "ENTER" if quality_tier in ("STRONG", "MODERATE") else "WAIT"

    return QualityAssessment(
        quality_score    = blended,
        quality_tier     = quality_tier,
        anti_fake_status = anti_fake_status,
        recommendation   = recommendation,
        red_flags        = red_flags,
        green_flags      = green_flags,
    )
