"""
Rolling Beta Gate — proxy de correlación sin Johansen/Engle-Granger.

Calcula beta rolling del activo vs BTC en ventana de N velas.
Si beta > 0.8 y el portfolio ya tiene exposición a BTC/ETH alta,
reduce sizing o emite caution para evitar sobre-correlación.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# ── Constants ──────────────────────────────────────────────
BETA_HIGH_THRESHOLD = 1.00
BETA_EXTREME_THRESHOLD = 2.50   # only block extreme outliers
REDUCE_SIZING_PCT = 0.70        # reduce to 70% if high beta + existing BTC exposure
MAX_BENCHMARK_POSITIONS = 3     # block only if 3+ benchmark positions already open
BENCHMARK_SYMBOL = "BTC/USDT:USDT"
BENCHMARK_TICKERS = ("BTCUSDT", "BTC/USDT", "BTC/USDT:USDT")


def _returns(prices: list[float]) -> list[float]:
    """Simple returns: (p[i] - p[i-1]) / p[i-1]"""
    if len(prices) < 2:
        return []
    return [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _covariance(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx = _mean(x)
    my = _mean(y)
    return sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / len(x)


def _variance(x: list[float]) -> float:
    if len(x) < 2:
        return 0.0
    mx = _mean(x)
    return sum((xi - mx) ** 2 for xi in x) / len(x)


def compute_beta(symbol_prices: list[float], benchmark_prices: list[float]) -> float | None:
    """
    Compute rolling beta = cov(ret_symbol, ret_benchmark) / var(ret_benchmark).
    Returns None if insufficient data.
    """
    if len(symbol_prices) < 10 or len(benchmark_prices) < 10:
        return None

    # Align lengths
    min_len = min(len(symbol_prices), len(benchmark_prices))
    sym = symbol_prices[-min_len:]
    bench = benchmark_prices[-min_len:]

    r_sym = _returns(sym)
    r_bench = _returns(bench)

    if len(r_sym) < 5 or len(r_bench) < 5:
        return None

    cov = _covariance(r_sym, r_bench)
    var = _variance(r_bench)

    if var == 0:
        return None

    beta = cov / var
    return beta


def _is_benchmark_symbol(sym: str, benchmark_symbols: tuple = BENCHMARK_TICKERS) -> bool:
    return any(b.upper() in (sym or "").upper() for b in benchmark_symbols)


def count_benchmark_positions(db: Session, user_id, benchmark_symbols: tuple = BENCHMARK_TICKERS) -> int:
    """Count how many open positions are in benchmark symbols (BTC, ETH, etc.)."""
    from app.models.position import Position
    from app.models.bot_config import BotConfig
    from sqlalchemy import select, and_

    result = db.execute(
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            and_(
                BotConfig.user_id == user_id,
                Position.status == "open",
                Position.source.in_(["bot", "ai_bot"]),
            )
        )
    )
    positions = result.scalars().all()
    return sum(1 for p in positions if _is_benchmark_symbol(p.symbol, benchmark_symbols))


def has_benchmark_exposure(db: Session, user_id, benchmark_symbols: tuple = BENCHMARK_TICKERS) -> bool:
    """Check if user has open positions in BTC or major benchmark."""
    return count_benchmark_positions(db, user_id, benchmark_symbols) > 0


def rolling_beta_gate(
    db: Session,
    user_id,
    symbol: str,
    direction: str,
    symbol_prices: list[float],
    benchmark_prices: list[float],
    user_cfg: dict | None = None,
) -> dict:
    """
    Evaluate rolling beta gate.
    Returns dict with blocked, caution, sizing_multiplier, reason.
    Accepts user_cfg with rolling_beta_threshold_multiplier.
    """
    beta = compute_beta(symbol_prices, benchmark_prices)

    if beta is None:
        return {"blocked": False, "caution": False, "sizing_multiplier": 1.0, "reason": None, "beta": None}

    mult = float(user_cfg.get("rolling_beta_threshold_multiplier", 1.0)) if user_cfg else 1.0
    high_th = BETA_HIGH_THRESHOLD * mult
    extreme_th = BETA_EXTREME_THRESHOLD * mult

    blocked = False
    caution = False
    sizing_mult = 1.0
    reasons = []

    # Check existing benchmark exposure
    has_btc = has_benchmark_exposure(db, user_id)

    benchmark_count = count_benchmark_positions(db, user_id)

    # Never block based on beta alone — only reduce sizing.
    if abs(beta) >= extreme_th:
        caution = True
        sizing_mult = REDUCE_SIZING_PCT
        reasons.append(f"Beta {beta:.2f} extreme (th={extreme_th:.2f}) — sizing reduced to {REDUCE_SIZING_PCT:.0%}")
    elif abs(beta) >= high_th:
        if has_btc:
            caution = True
            sizing_mult = REDUCE_SIZING_PCT
            reasons.append(f"Beta {beta:.2f} + BTC exposure (th={high_th:.2f}) — sizing reduced to {REDUCE_SIZING_PCT:.0%}")
        else:
            caution = True
            reasons.append(f"Beta {beta:.2f} high correlation with BTC (th={high_th:.2f})")

    return {
        "blocked": blocked,
        "caution": caution,
        "sizing_multiplier": sizing_mult,
        "reason": "; ".join(reasons) if reasons else None,
        "beta": round(beta, 3),
    }
