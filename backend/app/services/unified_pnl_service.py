"""Unified PnL service.

Provides a single source of truth for realised PnL by combining:
  - ExchangeTrade rows (real exchange executions, canonical)
  - Position rows (paper trades, fallback when no exchange trade exists)

This removes the double-counting that happens when endpoints mix
ExchangeTrade + Position for the same real close, and guarantees that
analytics endpoints speak the same language.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import cast, Date, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot_config import BotConfig
from app.models.exchange_trade import ExchangeTrade
from app.models.position import Position
from app.schemas.analytics import TradeSummary


@dataclass(frozen=True)
class UnifiedTrade:
    """Normalised closed-trade record used across analytics endpoints."""

    id: uuid.UUID
    symbol: str
    side: str
    realized_pnl: Decimal
    fee: Decimal | None
    quantity: Decimal | None
    entry_price: Decimal | None
    exit_price: Decimal | None
    opened_at: datetime | None
    closed_at: datetime | None
    is_paper: bool
    source: str
    bot_id: uuid.UUID | None
    position_id: uuid.UUID | None


def _normalize_symbol(symbol: str | None) -> str | None:
    if not symbol:
        return None
    return symbol.upper().replace("/USDT:USDT", "USDT")


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _closed_at_date(t: UnifiedTrade) -> date | None:
    if t.closed_at is None:
        return None
    return t.closed_at.date()


async def _fetch_exchange_trades(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    bot_id: uuid.UUID | None = None,
    symbol: str | None = None,
    source: str | None = None,
    source_in: Sequence[str] | None = None,
    exclude_sources: Sequence[str] | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    order_desc: bool = False,
) -> list[UnifiedTrade]:
    """Fetch canonical real trades from ExchangeTrade."""
    query = select(ExchangeTrade).where(
        ExchangeTrade.status == "closed",
        ExchangeTrade.closed_at.is_not(None),
        ExchangeTrade.realized_pnl.is_not(None),
    )

    if user_id:
        query = query.where(ExchangeTrade.user_id == user_id)
    if bot_id:
        query = query.where(ExchangeTrade.bot_id == bot_id)
    if symbol:
        query = query.where(ExchangeTrade.symbol == symbol)
    if source:
        query = query.where(ExchangeTrade.source == source)
    elif source_in:
        query = query.where(ExchangeTrade.source.in_(source_in))
    if exclude_sources:
        query = query.where(ExchangeTrade.source.notin_(exclude_sources))

    if from_date:
        query = query.where(cast(ExchangeTrade.closed_at, Date) >= from_date)
    if to_date:
        query = query.where(cast(ExchangeTrade.closed_at, Date) <= to_date)

    order_col = ExchangeTrade.closed_at.desc() if order_desc else ExchangeTrade.closed_at.asc()
    query = query.order_by(order_col)

    result = await db.execute(query)
    rows = result.scalars().all()

    return [
        UnifiedTrade(
            id=t.id,
            symbol=t.symbol or "",
            side=t.side or "long",
            realized_pnl=_to_decimal(t.realized_pnl),
            fee=_to_decimal(t.fee) if t.fee is not None else None,
            quantity=_to_decimal(t.quantity) if t.quantity is not None else None,
            entry_price=_to_decimal(t.entry_price) if t.entry_price is not None else None,
            exit_price=_to_decimal(t.exit_price) if t.exit_price is not None else None,
            opened_at=t.opened_at,
            closed_at=t.closed_at,
            is_paper=False,
            source=t.source or "unknown",
            bot_id=t.bot_id,
            position_id=t.position_id,
        )
        for t in rows
    ]


async def _fetch_paper_positions(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    bot_id: uuid.UUID | None = None,
    symbol: str | None = None,
    source: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    order_desc: bool = False,
) -> list[UnifiedTrade]:
    """Fetch paper trades from Position (bots with a paper balance)."""
    query = (
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            BotConfig.paper_balance_id.is_not(None),
            Position.status == "closed",
            Position.closed_at.is_not(None),
            Position.realized_pnl.is_not(None),
        )
    )

    if user_id:
        query = query.where(BotConfig.user_id == user_id)
    if bot_id:
        query = query.where(Position.bot_id == bot_id)
    if symbol:
        query = query.where(Position.symbol == symbol)
    if source:
        query = query.where(Position.source == source)

    if from_date:
        query = query.where(cast(Position.closed_at, Date) >= from_date)
    if to_date:
        query = query.where(cast(Position.closed_at, Date) <= to_date)

    order_col = Position.closed_at.desc() if order_desc else Position.closed_at.asc()
    query = query.order_by(order_col)

    result = await db.execute(query)
    rows = result.scalars().all()

    return [
        UnifiedTrade(
            id=p.id,
            symbol=p.symbol or "",
            side=p.side or "long",
            realized_pnl=_to_decimal(p.realized_pnl),
            fee=None,
            quantity=_to_decimal(p.quantity) if p.quantity is not None else None,
            entry_price=_to_decimal(p.entry_price) if p.entry_price is not None else None,
            exit_price=None,
            opened_at=p.opened_at,
            closed_at=p.closed_at,
            is_paper=True,
            source=p.source or "ai_bot",
            bot_id=p.bot_id,
            position_id=p.id,
        )
        for p in rows
    ]


async def get_closed_trades_unified(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    bot_id: uuid.UUID | None = None,
    symbol: str | None = None,
    source: str | None = None,
    source_in: Sequence[str] | None = None,
    exclude_sources: Sequence[str] | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    mode: str = "total",
    order_desc: bool = False,
    limit: int | None = None,
) -> list[UnifiedTrade]:
    """Return a deduplicated, ordered list of closed trades.

    mode:
      - "real":   ExchangeTrade rows only (canonical real executions)
      - "paper":  Position rows for paper bots only
      - "total":  real ExchangeTrade + paper Position rows

    source/source_in/exclude_sources apply to the underlying source column.
    When source == "paper", mode is forced to "paper".
    """
    if mode not in {"real", "paper", "total"}:
        raise ValueError("mode must be one of: real, paper, total")

    if source == "paper":
        mode = "paper"

    symbol = _normalize_symbol(symbol)

    trades: list[UnifiedTrade] = []

    if mode in ("real", "total"):
        trades.extend(
            await _fetch_exchange_trades(
                db,
                user_id=user_id,
                bot_id=bot_id,
                symbol=symbol,
                source=source,
                source_in=source_in,
                exclude_sources=exclude_sources,
                from_date=from_date,
                to_date=to_date,
                order_desc=order_desc,
            )
        )

    if mode in ("paper", "total"):
        trades.extend(
            await _fetch_paper_positions(
                db,
                user_id=user_id,
                bot_id=bot_id,
                symbol=symbol,
                source=source,
                from_date=from_date,
                to_date=to_date,
                order_desc=order_desc,
            )
        )

    # Sort by closed_at (stable); limit afterwards to keep chronological slices intact
    trades.sort(key=lambda t: (t.closed_at or datetime.min), reverse=order_desc)

    if limit:
        trades = trades[:limit]

    return trades


async def get_recent_closed_trades_unified(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    bot_id: uuid.UUID | None = None,
    symbol: str | None = None,
    source: str | None = None,
    source_in: Sequence[str] | None = None,
    exclude_sources: Sequence[str] | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    mode: str = "total",
    limit: int = 100,
) -> list[UnifiedTrade]:
    """Convenience wrapper that returns the most recent closed trades first."""
    return await get_closed_trades_unified(
        db,
        user_id=user_id,
        bot_id=bot_id,
        symbol=symbol,
        source=source,
        source_in=source_in,
        exclude_sources=exclude_sources,
        from_date=from_date,
        to_date=to_date,
        mode=mode,
        order_desc=True,
        limit=limit,
    )


def compute_summary_from_unified(trades: Iterable[UnifiedTrade]) -> TradeSummary:
    """Compute TradeSummary from a list of UnifiedTrade records."""
    zero = Decimal("0")
    trades = list(trades)

    if not trades:
        return TradeSummary(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            profit_factor=None,
            total_pnl=zero,
            average_pnl=zero,
            best_trade=zero,
            worst_trade=zero,
            max_drawdown=zero,
            avg_duration_hours=0.0,
            current_streak=0,
            long_trades=0,
            short_trades=0,
            long_win_rate=0.0,
            short_win_rate=0.0,
            long_pnl=zero,
            short_pnl=zero,
        )

    pnls = [t.realized_pnl for t in trades]
    total = len(pnls)

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n_wins = len(wins)

    total_win = sum(wins, zero)
    total_loss = abs(sum(losses, zero))
    profit_factor = round(float(total_win / total_loss), 2) if total_loss > 0 else None

    # Max drawdown from equity peak
    cumulative = zero
    peak = zero
    max_dd = zero
    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Current streak
    streak = 0
    for t in reversed(trades):
        if t.realized_pnl is None:
            break
        if t.realized_pnl > 0:
            if streak < 0:
                break
            streak += 1
        else:
            if streak > 0:
                break
            streak -= 1

    # Duration
    durations: list[float] = []
    for t in trades:
        if t.opened_at and t.closed_at:
            durations.append((t.closed_at - t.opened_at).total_seconds() / 3600)
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

    # Long / Short
    longs = [t for t in trades if t.side == "long"]
    shorts = [t for t in trades if t.side == "short"]

    long_wins = sum(1 for t in longs if t.realized_pnl > 0)
    short_wins = sum(1 for t in shorts if t.realized_pnl > 0)
    long_pnl = sum((t.realized_pnl for t in longs), zero)
    short_pnl = sum((t.realized_pnl for t in shorts), zero)

    return TradeSummary(
        total_trades=total,
        winning_trades=n_wins,
        losing_trades=total - n_wins,
        win_rate=round(n_wins / total, 4),
        profit_factor=profit_factor,
        total_pnl=sum(pnls, zero),
        average_pnl=sum(pnls, zero) / total,
        best_trade=max(pnls),
        worst_trade=min(pnls),
        max_drawdown=max_dd,
        avg_duration_hours=avg_duration,
        current_streak=streak,
        long_trades=len(longs),
        short_trades=len(shorts),
        long_win_rate=round(long_wins / len(longs), 4) if longs else 0.0,
        short_win_rate=round(short_wins / len(shorts), 4) if shorts else 0.0,
        long_pnl=long_pnl,
        short_pnl=short_pnl,
    )


def build_daily_pnl_curve(trades: Iterable[UnifiedTrade]) -> list[dict]:
    """Build a daily cumulative PnL curve from closed trades.

    Returns a list of dicts with keys: date, daily_pnl, cumulative_pnl, trade_count.
    Days without trades are NOT filled in here; callers can fill the range if needed.
    """
    daily: dict[str, Decimal] = {}
    counts: dict[str, int] = {}

    for t in trades:
        if not t.closed_at:
            continue
        ds = t.closed_at.strftime("%Y-%m-%d")
        daily[ds] = daily.get(ds, Decimal("0")) + t.realized_pnl
        counts[ds] = counts.get(ds, 0) + 1

    cumulative = Decimal("0")
    curve: list[dict] = []
    for ds in sorted(daily.keys()):
        cumulative += daily[ds]
        curve.append(
            {
                "date": ds,
                "daily_pnl": round(daily[ds], 4),
                "cumulative_pnl": round(cumulative, 4),
                "trade_count": counts.get(ds, 0),
            }
        )
    return curve


def fill_daily_curve(
    curve: list[dict],
    since: date,
    until: date,
) -> list[dict]:
    """Fill missing days in a daily curve with zero PnL."""
    by_date = {row["date"]: row for row in curve}
    cumulative = Decimal("0")
    filled: list[dict] = []
    cursor = since
    while cursor <= until:
        ds = cursor.strftime("%Y-%m-%d")
        if ds in by_date:
            cumulative = by_date[ds]["cumulative_pnl"]
            filled.append(
                {
                    "date": ds,
                    "daily_pnl": by_date[ds]["daily_pnl"],
                    "cumulative_pnl": round(cumulative, 4),
                    "trade_count": by_date[ds]["trade_count"],
                }
            )
        else:
            filled.append(
                {
                    "date": ds,
                    "daily_pnl": Decimal("0"),
                    "cumulative_pnl": round(cumulative, 4),
                    "trade_count": 0,
                }
            )
        cursor += timedelta(days=1)
    return filled
