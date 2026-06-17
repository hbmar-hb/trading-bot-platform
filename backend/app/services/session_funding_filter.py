"""
Filtro de Sesión / Funding Rate.

Sesiones (UTC):
- Asia:   00:00–08:00 UTC
- Londres: 08:00–16:00 UTC  
- NY:      16:00–00:00 UTC

Reglas de funding:
- |funding| > 0.10% → caution
- |funding| > 0.30% → block
- funding negativo extremo + long → block
- funding positivo extremo + short → block

Sesión gate (solo caution, nunca block por sesión):
- Asia + altcoin no-BTC/ETH → caution (spread amplio)
"""
from __future__ import annotations

from datetime import datetime, timezone

# ── Constantes ──────────────────────────────────────────────
FUNDING_CAUTION_PCT = 0.0010   # 0.10%
FUNDING_BLOCK_PCT = 0.0030     # 0.30%


def _current_session() -> str:
    """Devuelve la sesión de trading actual en UTC."""
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < 8:
        return "asia"
    elif 8 <= hour < 16:
        return "london"
    else:
        return "ny"


def session_funding_gate(
    symbol: str,
    funding_rate: float | None,
    direction: str,
) -> dict:
    """
    Evalúa sesión y funding rate para una señal.
    Devuelve dict con blocked, caution, reason, session.
    """
    blocked = False
    caution = False
    reasons = []
    session = _current_session()

    # ── Funding gate ──
    if funding_rate is None:
        return {
            "blocked": False,
            "caution": False,
            "reason": None,
            "session": session,
            "funding_rate": None,
        }

    abs_funding = abs(funding_rate)
    if abs_funding >= FUNDING_BLOCK_PCT:
        blocked = True
        reasons.append(
            f"Funding {funding_rate:+.2%} >= {FUNDING_BLOCK_PCT:.2%}"
        )
    elif abs_funding >= FUNDING_CAUTION_PCT:
        caution = True
        reasons.append(
            f"Funding {funding_rate:+.2%} >= {FUNDING_CAUTION_PCT:.2%}"
        )

    # Funding direccional
    if funding_rate > FUNDING_BLOCK_PCT and direction == "long":
        blocked = True
        reasons.append(f"Extreme positive funding + long: {funding_rate:+.2%}")
    elif funding_rate < -FUNDING_BLOCK_PCT and direction == "short":
        blocked = True
        reasons.append(f"Extreme negative funding + short: {funding_rate:+.2%}")

    # ── Session gate (solo caution) ──
    if session == "asia":
        base = symbol.split("/")[0] if "/" in symbol else symbol
        base = base.replace("USDT", "").replace("USDC", "").replace("USD", "")
        if base not in ("BTC", "ETH"):
            caution = True
            reasons.append("Asia session + altcoin (wide spreads)")

    return {
        "blocked": blocked,
        "caution": caution,
        "reason": "; ".join(reasons) if reasons else None,
        "session": session,
        "funding_rate": round(funding_rate, 6),
    }
