"""Signal quality assessment — Fase 1.5 (heuristic anti-fake layer).

Runs after confluence analysis using the already-computed ConfluenceResult
features.  No ML model required.

Scoring (max ~105, capped at 100):
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

Quality tiers: STRONG ≥70 | MODERATE ≥45 | WEAK <45
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
    red_flags:        list[str]  = field(default_factory=list)
    green_flags:      list[str]  = field(default_factory=list)


def assess_quality(result: ConfluenceResult) -> QualityAssessment:
    """Evaluate signal quality from an existing ConfluenceResult."""
    f         = result.features
    direction = result.direction

    green_flags: list[str] = []
    red_flags:   list[str] = []
    score = 0.0

    # ── Volume confirmation ───────────────────────────────────────────────────
    vol_ratio = f.get("volume_ratio", 1.0)
    if vol_ratio > 1.5:
        score += 15
        green_flags.append(f"Volumen {vol_ratio:.1f}× sobre media — confirmación fuerte")
    elif vol_ratio > 1.0:
        score += 7
        green_flags.append(f"Volumen {vol_ratio:.1f}× sobre media")
    elif vol_ratio < 0.5:
        red_flags.append(f"Volumen {vol_ratio:.1f}× — falta de interés del mercado")

    # ── Spread / candle quality ───────────────────────────────────────────────
    spread_atr = f.get("spread_atr", 0.0)
    if spread_atr < 1.0:
        score += 15
        green_flags.append("Estructura de vela limpia (spread < 1×ATR)")
    elif spread_atr < 1.5:
        score += 7
    elif spread_atr > 2.0:
        red_flags.append(f"Spread {spread_atr:.1f}×ATR — posible spike / manipulación")

    # ── Liquidity sweep ───────────────────────────────────────────────────────
    if f.get("sweep_detected"):
        score += 20
        sweep_type = f.get("sweep_type") or ""
        green_flags.append(
            f"Liquidity sweep {'BSL' if sweep_type == 'BSL' else 'SSL'} confirmado"
        )

    # ── Aligned FVGs ─────────────────────────────────────────────────────────
    fvg_n = f.get("fvg_aligned_count", 0)
    if fvg_n >= 2:
        score += 15
        green_flags.append(f"{fvg_n} FVGs alineados sin llenar")
    elif fvg_n == 1:
        score += 8
        green_flags.append("FVG alineado sin llenar")

    # ── Killzone ──────────────────────────────────────────────────────────────
    kz = f.get("killzone")
    if kz:
        score += 15
        green_flags.append(f"Killzone {kz} activa — timing óptimo")

    # ── Premium / Discount position ───────────────────────────────────────────
    pd_pos = f.get("pd_position", 0.5)
    if direction == "long":
        if pd_pos < 0.35:
            score += 15
            green_flags.append(f"Zona discount profunda ({pd_pos:.0%})")
        elif pd_pos < 0.5:
            score += 8
            green_flags.append(f"Zona discount ({pd_pos:.0%})")
    else:
        if pd_pos > 0.65:
            score += 15
            green_flags.append(f"Zona premium alta ({pd_pos:.0%})")
        elif pd_pos > 0.5:
            score += 8
            green_flags.append(f"Zona premium ({pd_pos:.0%})")

    # ── Entry trigger quality ─────────────────────────────────────────────────
    trigger = f.get("trigger")
    if trigger == "ob":
        score += 10
        green_flags.append("Order Block como trigger preciso")
    elif trigger == "fvg":
        score += 5
        green_flags.append("FVG como trigger")

    score = round(min(100.0, max(0.0, score)), 1)

    if score >= 70:
        quality_tier = "STRONG"
    elif score >= 45:
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
        recommendation   = "ENTER" if quality_tier == "STRONG" else "WAIT"

    return QualityAssessment(
        quality_score    = score,
        quality_tier     = quality_tier,
        anti_fake_status = anti_fake_status,
        recommendation   = recommendation,
        red_flags        = red_flags,
        green_flags      = green_flags,
    )
