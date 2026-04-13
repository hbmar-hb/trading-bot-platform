import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import cast, Date, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id
from app.models.bot_config import BotConfig
from app.models.exchange_trade import ExchangeTrade
from app.models.position import Position
from app.schemas.analytics import (
    ActivityPoint,
    AnalyticsSummaryResponse,
    BotStats,
    DailyPnlPoint,
    EquityPoint,
    HourlyStats,
    TradeSummary,
)
from app.services.database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def get_summary(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Estadísticas globales + por bot + curva de equity."""

    closed = await db.execute(
        select(Position, BotConfig)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            BotConfig.user_id == user_id,
            Position.status == "closed",
            Position.realized_pnl.is_not(None),
        )
        .order_by(Position.closed_at)
    )
    rows = closed.all()

    global_stats = _compute_summary([pos for pos, _ in rows])

    # ── Stats por bot ─────────────────────────────────────────
    bots_map: dict[uuid.UUID, list[Position]] = {}
    for pos, bot in rows:
        bots_map.setdefault(bot.id, []).append(pos)

    all_bots_result = await db.execute(
        select(BotConfig).where(
            BotConfig.user_id == user_id,
            ~BotConfig.bot_name.like("[MANUAL]%"),
        )
    )
    all_bots = {b.id: b for b in all_bots_result.scalars()}

    by_bot: list[BotStats] = []
    for bot_id, positions in bots_map.items():
        bot = all_bots.get(bot_id)
        if not bot:
            continue
        stats = _compute_summary(positions)
        by_bot.append(BotStats(
            bot_id=bot.id,
            bot_name=bot.bot_name,
            symbol=bot.symbol,
            status=bot.status,
            total_trades=stats.total_trades,
            winning_trades=stats.winning_trades,
            win_rate=stats.win_rate,
            profit_factor=stats.profit_factor,
            total_pnl=stats.total_pnl,
            avg_pnl=stats.average_pnl,
            best_trade=stats.best_trade,
            worst_trade=stats.worst_trade,
        ))

    # Bots sin trades
    for bot_id, bot in all_bots.items():
        if bot_id not in bots_map:
            zero = Decimal("0")
            by_bot.append(BotStats(
                bot_id=bot.id, bot_name=bot.bot_name, symbol=bot.symbol,
                status=bot.status, total_trades=0, winning_trades=0,
                win_rate=0.0, profit_factor=None, total_pnl=zero,
                avg_pnl=zero, best_trade=zero, worst_trade=zero,
            ))

    # Ordenar: más trades primero
    by_bot.sort(key=lambda b: b.total_trades, reverse=True)

    # ── Curva de equity ───────────────────────────────────────
    equity_curve: list[EquityPoint] = []
    cumulative = Decimal("0")
    for pos, _ in rows:
        if pos.closed_at and pos.realized_pnl is not None:
            cumulative += pos.realized_pnl
            equity_curve.append(EquityPoint(
                timestamp=pos.closed_at,
                cumulative_pnl=cumulative,
                trade_pnl=pos.realized_pnl,
                symbol=pos.symbol,
                side=pos.side,
            ))

    return AnalyticsSummaryResponse(
        global_stats=global_stats,
        by_bot=by_bot,
        equity_curve=equity_curve,
    )


@router.get("/bots/{bot_id}", response_model=BotStats)
async def get_bot_stats(
    bot_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Position, BotConfig)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            BotConfig.id == bot_id,
            BotConfig.user_id == user_id,
            Position.status == "closed",
        )
    )
    rows = result.all()
    zero = Decimal("0")

    if not rows:
        bot_result = await db.execute(
            select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user_id)
        )
        bot = bot_result.scalar_one_or_none()
        return BotStats(
            bot_id=bot.id, bot_name=bot.bot_name, symbol=bot.symbol,
            status=bot.status, total_trades=0, winning_trades=0,
            win_rate=0.0, profit_factor=None, total_pnl=zero,
            avg_pnl=zero, best_trade=zero, worst_trade=zero,
        )

    positions = [pos for pos, _ in rows]
    bot = rows[0][1]
    stats = _compute_summary(positions)

    return BotStats(
        bot_id=bot.id, bot_name=bot.bot_name, symbol=bot.symbol,
        status=bot.status, total_trades=stats.total_trades,
        winning_trades=stats.winning_trades, win_rate=stats.win_rate,
        profit_factor=stats.profit_factor, total_pnl=stats.total_pnl,
        avg_pnl=stats.average_pnl, best_trade=stats.best_trade,
        worst_trade=stats.worst_trade,
    )


@router.get("/symbols")
async def get_traded_symbols(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExchangeTrade.symbol)
        .where(ExchangeTrade.user_id == user_id)
        .distinct()
        .order_by(ExchangeTrade.symbol)
    )
    return {"symbols": [r[0] for r in result.all()]}


@router.get("/pnl-chart", response_model=list[DailyPnlPoint])
async def get_pnl_chart(
    from_date: date | None = Query(None),
    to_date:   date | None = Query(None),
    symbol:    str | None  = Query(None),
    source:    str | None  = Query(None),
    bot_id:    uuid.UUID | None = Query(None),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """PnL diario + acumulado desde exchange_trades."""
    day_col = cast(ExchangeTrade.closed_at, Date).label("day")

    query = (
        select(
            day_col,
            func.sum(func.coalesce(ExchangeTrade.realized_pnl, 0)).label("daily_pnl"),
            func.count().label("trade_count"),
        )
        .where(
            ExchangeTrade.user_id == user_id,
            ExchangeTrade.closed_at.is_not(None),
            ExchangeTrade.realized_pnl.is_not(None),
            ExchangeTrade.realized_pnl != 0,
        )
    )

    if from_date:
        query = query.where(cast(ExchangeTrade.closed_at, Date) >= from_date)
    if to_date:
        query = query.where(cast(ExchangeTrade.closed_at, Date) <= to_date)
    if symbol:
        query = query.where(ExchangeTrade.symbol == symbol)
    if source == "manual":
        query = query.where(ExchangeTrade.source == "manual")
    elif source == "bots":
        query = query.where(ExchangeTrade.source == "bot")
    if bot_id:
        query = query.where(ExchangeTrade.bot_id == bot_id)

    query = query.group_by(day_col).order_by(day_col)
    result = await db.execute(query)
    rows = result.all()

    cumulative = Decimal("0")
    points: list[DailyPnlPoint] = []
    for row in rows:
        daily = row.daily_pnl or Decimal("0")
        cumulative += daily
        points.append(DailyPnlPoint(
            date=str(row.day),
            daily_pnl=daily,
            cumulative_pnl=cumulative,
            trade_count=row.trade_count,
        ))
    return points


@router.get("/activity-heatmap", response_model=list[ActivityPoint])
async def get_activity_heatmap(
    from_date: date | None = Query(None),
    to_date:   date | None = Query(None),
    bot_id:    uuid.UUID | None = Query(None),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Heatmap de actividad: trades por día (para gráfico tipo GitHub)."""
    day_col = cast(ExchangeTrade.closed_at, Date).label("day")

    query = (
        select(
            day_col,
            func.count().label("trade_count"),
            func.sum(func.coalesce(ExchangeTrade.realized_pnl, 0)).label("daily_pnl")
        )
        .where(
            ExchangeTrade.user_id == user_id,
            ExchangeTrade.closed_at.is_not(None),
        )
    )

    if from_date:
        query = query.where(cast(ExchangeTrade.closed_at, Date) >= from_date)
    if to_date:
        query = query.where(cast(ExchangeTrade.closed_at, Date) <= to_date)
    if bot_id:
        query = query.where(ExchangeTrade.bot_id == bot_id)

    query = query.group_by(day_col).order_by(day_col)
    result = await db.execute(query)
    rows = result.all()

    return [
        ActivityPoint(
            date=str(row.day),
            count=row.trade_count,
            pnl=row.daily_pnl or Decimal("0")
        )
        for row in rows
    ]


@router.get("/hourly-distribution", response_model=list[HourlyStats])
async def get_hourly_distribution(
    from_date: date | None = Query(None),
    to_date:   date | None = Query(None),
    bot_id:    uuid.UUID | None = Query(None),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Distribución de trades por hora del día (0-23)."""
    hour_col = func.extract('hour', ExchangeTrade.closed_at).label("hour")

    query = (
        select(
            hour_col,
            func.count().label("trade_count"),
            func.sum(func.coalesce(ExchangeTrade.realized_pnl, 0)).label("hourly_pnl")
        )
        .where(
            ExchangeTrade.user_id == user_id,
            ExchangeTrade.closed_at.is_not(None),
            ExchangeTrade.realized_pnl.is_not(None),
        )
    )

    if from_date:
        query = query.where(cast(ExchangeTrade.closed_at, Date) >= from_date)
    if to_date:
        query = query.where(cast(ExchangeTrade.closed_at, Date) <= to_date)
    if bot_id:
        query = query.where(ExchangeTrade.bot_id == bot_id)

    query = query.group_by(hour_col).order_by(hour_col)
    result = await db.execute(query)
    rows = result.all()

    # Calcular wins por hora (subquery separada para accuracy)
    wins_query = (
        select(
            func.extract('hour', ExchangeTrade.closed_at).label("hour"),
            func.count().label("win_count")
        )
        .where(
            ExchangeTrade.user_id == user_id,
            ExchangeTrade.closed_at.is_not(None),
            ExchangeTrade.realized_pnl > 0,
        )
    )
    if from_date:
        wins_query = wins_query.where(cast(ExchangeTrade.closed_at, Date) >= from_date)
    if to_date:
        wins_query = wins_query.where(cast(ExchangeTrade.closed_at, Date) <= to_date)
    if bot_id:
        wins_query = wins_query.where(ExchangeTrade.bot_id == bot_id)
    wins_query = wins_query.group_by(func.extract('hour', ExchangeTrade.closed_at))

    wins_result = await db.execute(wins_query)
    wins_by_hour = {int(row.hour): row.win_count for row in wins_result.all()}

    return [
        HourlyStats(
            hour=int(row.hour),
            trades=row.trade_count,
            wins=wins_by_hour.get(int(row.hour), 0),
            pnl=row.hourly_pnl or Decimal("0"),
            win_rate=round(wins_by_hour.get(int(row.hour), 0) / row.trade_count, 4) if row.trade_count > 0 else 0.0
        )
        for row in rows
    ]


# ─── Helpers ─────────────────────────────────────────────────

def _compute_summary(positions: list[Position]) -> TradeSummary:
    zero = Decimal("0")

    if not positions:
        return TradeSummary(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0.0, profit_factor=None, total_pnl=zero,
            average_pnl=zero, best_trade=zero, worst_trade=zero,
            max_drawdown=zero, avg_duration_hours=0.0, current_streak=0,
            long_trades=0, short_trades=0, long_win_rate=0.0,
            short_win_rate=0.0, long_pnl=zero, short_pnl=zero,
        )

    pnls = [p.realized_pnl for p in positions if p.realized_pnl is not None]
    total = len(pnls)
    if total == 0:
        return _compute_summary([])

    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n_wins = len(wins)

    total_win  = sum(wins,   zero)
    total_loss = abs(sum(losses, zero))
    profit_factor = round(float(total_win / total_loss), 2) if total_loss > 0 else None

    # Max drawdown (desde el pico de equity acumulado)
    cumulative = zero
    peak       = zero
    max_dd     = zero
    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Duración media
    durations = []
    for p in positions:
        if p.realized_pnl is not None and p.opened_at and p.closed_at:
            durations.append((p.closed_at - p.opened_at).total_seconds() / 3600)
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

    # Racha actual (+ wins, - losses)
    streak = 0
    for p in reversed(positions):
        if p.realized_pnl is None:
            break
        if p.realized_pnl > 0:
            if streak < 0:
                break
            streak += 1
        else:
            if streak > 0:
                break
            streak -= 1

    # Long vs Short
    longs  = [p for p in positions if p.side == "long"  and p.realized_pnl is not None]
    shorts = [p for p in positions if p.side == "short" and p.realized_pnl is not None]

    long_wins  = sum(1 for p in longs  if p.realized_pnl > 0)
    short_wins = sum(1 for p in shorts if p.realized_pnl > 0)
    long_pnl   = sum((p.realized_pnl for p in longs),  zero)
    short_pnl  = sum((p.realized_pnl for p in shorts), zero)

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
        long_win_rate=round(long_wins  / len(longs),  4) if longs  else 0.0,
        short_win_rate=round(short_wins / len(shorts), 4) if shorts else 0.0,
        long_pnl=long_pnl,
        short_pnl=short_pnl,
    )
