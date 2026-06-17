"""
Dashboard de Salud Institucional — métricas de riesgo-retorno de nivel institucional.

Calcula:
- Sharpe Ratio (anualizado)
- Sortino Ratio (anualizado)
- Calmar Ratio
- Ulcer Index
- Risk of Ruin (Monte Carlo)
- Time-to-Recovery (TtR)
- Max Drawdown
- Profit Factor
- Expectancy
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class HealthMetrics:
    sharpe_ratio: float | None
    sortino_ratio: float | None
    calmar_ratio: float | None
    ulcer_index: float | None
    risk_of_ruin_pct: float | None
    time_to_recovery_days: float | None
    max_drawdown_pct: float | None
    profit_factor: float | None
    expectancy_pct: float | None
    win_rate: float | None
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float | None
    avg_loss: float | None


def _daily_returns_from_trades(trades: list) -> list[float]:
    """Aggregate trade PnLs into daily returns."""
    from collections import defaultdict
    daily: defaultdict[str, float] = defaultdict(float)
    for t in trades:
        if t.closed_at:
            day = t.closed_at.strftime("%Y-%m-%d")
            daily[day] += float(t.realized_pnl or 0)
    return list(daily.values())


def _daily_returns_from_equity(equity_curve: list[dict]) -> list[float]:
    """Extract daily returns from equity curve."""
    if not equity_curve:
        return []
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1].get("cumulative_pnl", 0)
        curr = equity_curve[i].get("cumulative_pnl", 0)
        daily = curr - prev
        # approximate equity base as average cumulative up to prev
        base = max(abs(prev), 100.0)  # avoid div by zero
        returns.append(daily / base)
    return returns


def _sharpe(returns: list[float], risk_free_rate: float = 0.0, periods_per_year: float = 365.0) -> float | None:
    if len(returns) < 2:
        return None
    mean_r = sum(returns) / len(returns)
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / len(returns))
    if std_r == 0:
        return None
    return (mean_r - risk_free_rate) / std_r * math.sqrt(periods_per_year)


def _sortino(returns: list[float], risk_free_rate: float = 0.0, periods_per_year: float = 365.0) -> float | None:
    if len(returns) < 2:
        return None
    mean_r = sum(returns) / len(returns)
    downside = [r for r in returns if r < risk_free_rate]
    if not downside:
        return float("inf")
    downside_std = math.sqrt(sum((r - risk_free_rate) ** 2 for r in downside) / len(downside))
    if downside_std == 0:
        return None
    return (mean_r - risk_free_rate) / downside_std * math.sqrt(periods_per_year)


def _calmar(returns: list[float], max_dd_pct: float) -> float | None:
    if not returns or max_dd_pct == 0:
        return None
    total_return = sum(returns)
    # approximate annualized return: total / days * 365
    # but we use total_return / max_drawdown as simple Calmar proxy
    return total_return / abs(max_dd_pct)


def _ulcer_index(equity_curve: list[float]) -> float | None:
    """Ulcer Index = sqrt(mean of squared drawdowns from peak)."""
    if not equity_curve:
        return None
    peak = equity_curve[0]
    sq_dd = []
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak != 0 else 0
        sq_dd.append(dd ** 2)
    return math.sqrt(sum(sq_dd) / len(sq_dd))


def _max_drawdown(equity_curve: list[float]) -> tuple[float, int]:
    """Returns (max_drawdown_pct, duration_in_days_approx)."""
    if not equity_curve:
        return 0.0, 0
    peak = equity_curve[0]
    max_dd = 0.0
    peak_idx = 0
    max_dd_duration = 0
    for i, val in enumerate(equity_curve):
        if val > peak:
            peak = val
            peak_idx = i
        dd = (peak - val) / peak if peak != 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_duration = i - peak_idx
    return max_dd, max_dd_duration


def _risk_of_ruin_monte_carlo(
    returns: list[float],
    ruin_threshold: float = -0.50,
    simulations: int = 1000,
    trades_per_sim: int = 200,
) -> float | None:
    """Monte Carlo Risk of Ruin. Returns % of simulations that hit ruin_threshold."""
    if len(returns) < 5:
        return None
    ruin_count = 0
    for _ in range(simulations):
        equity = 0.0
        for _ in range(trades_per_sim):
            ret = random.choice(returns)
            equity += ret
            if equity <= ruin_threshold:
                ruin_count += 1
                break
    return (ruin_count / simulations) * 100.0


def _time_to_recovery(equity_curve: list[float]) -> float | None:
    """Average days from peak to recovery (new high)."""
    if not equity_curve:
        return None
    peak = equity_curve[0]
    in_dd = False
    dd_start = 0
    recoveries = []
    for i, val in enumerate(equity_curve):
        if val >= peak:
            if in_dd:
                recoveries.append(i - dd_start)
                in_dd = False
            peak = val
        else:
            if not in_dd:
                in_dd = True
                dd_start = i
    if not recoveries:
        return None
    return sum(recoveries) / len(recoveries)


# Reference capital for drawdown calculations (avoids absurd % with micro-PnLs)
_REFERENCE_CAPITAL = 10000.0


def compute_institutional_health(
    db: Session | None,
    trades: list | None = None,
    equity_curve: list[dict] | None = None,
    reference_capital: float = _REFERENCE_CAPITAL,
) -> HealthMetrics:
    """
    Compute full institutional health metrics.
    Pass either trades (list of ExchangeTrade/Position) or equity_curve.

    reference_capital: base equity used to normalize drawdown percentages.
                       Default 10k USDT prevents absurd drawdowns when
                       trading with small sizes.
    """
    if trades is None and equity_curve is None:
        return HealthMetrics(
            sharpe_ratio=None, sortino_ratio=None, calmar_ratio=None,
            ulcer_index=None, risk_of_ruin_pct=None, time_to_recovery_days=None,
            max_drawdown_pct=None, profit_factor=None, expectancy_pct=None,
            win_rate=None, total_trades=0, winning_trades=0, losing_trades=0,
            avg_win=None, avg_loss=None,
        )

    # Extract PnL list
    pnls: list[float] = []
    if trades:
        pnls = [float(t.realized_pnl or 0) for t in trades if hasattr(t, "realized_pnl")]
    elif equity_curve:
        pnls = [d.get("daily_pnl", 0) for d in equity_curve]

    total_trades = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = len(wins) / total_trades * 100.0 if total_trades > 0 else None
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else None
    expectancy = (
        (len(wins) / total_trades * (avg_win or 0)) +
        (len(losses) / total_trades * (avg_loss or 0))
    ) if total_trades > 0 else None

    # Build equity curve anchored to reference_capital so drawdown % is sane
    eq_curve: list[float] = []
    if equity_curve:
        eq_curve = [reference_capital + d.get("cumulative_pnl", 0) for d in equity_curve]
    else:
        cum = reference_capital
        for p in pnls:
            cum += p
            eq_curve.append(cum)

    max_dd_pct, _ = _max_drawdown(eq_curve)
    ulcer = _ulcer_index(eq_curve)
    ttr = _time_to_recovery(eq_curve)

    # Daily returns for Sharpe/Sortino (percentage-based, not dollar-based)
    if equity_curve:
        daily_rets = _daily_returns_from_equity(equity_curve)
    else:
        # Convert dollar returns to % returns vs reference capital
        daily_rets = [p / reference_capital for p in pnls]

    sharpe = _sharpe(daily_rets)
    sortino = _sortino(daily_rets)
    calmar = _calmar(daily_rets, max_dd_pct)

    # Monte Carlo Risk of Ruin (use daily returns scaled)
    ror = _risk_of_ruin_monte_carlo(daily_rets) if len(daily_rets) >= 5 else None

    return HealthMetrics(
        sharpe_ratio=round(sharpe, 2) if sharpe is not None else None,
        sortino_ratio=round(sortino, 2) if sortino is not None else None,
        calmar_ratio=round(calmar, 2) if calmar is not None else None,
        ulcer_index=round(ulcer, 4) if ulcer is not None else None,
        risk_of_ruin_pct=round(ror, 1) if ror is not None else None,
        time_to_recovery_days=round(ttr, 1) if ttr is not None else None,
        max_drawdown_pct=round(max_dd_pct * 100, 2) if max_dd_pct is not None else None,
        profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
        expectancy_pct=round(expectancy, 4) if expectancy is not None else None,
        win_rate=round(win_rate, 1) if win_rate is not None else None,
        total_trades=total_trades,
        winning_trades=len(wins),
        losing_trades=len(losses),
        avg_win=round(avg_win, 4) if avg_win is not None else None,
        avg_loss=round(avg_loss, 4) if avg_loss is not None else None,
    )
