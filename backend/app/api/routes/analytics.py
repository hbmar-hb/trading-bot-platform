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
    AnalyticsSummaryResponse,
    BotStats,
    DailyPnlPoint,
    EquityPoint,
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

    # ── Posiciones cerradas del usuario ──────────────────────
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

    # ── Stats globales ────────────────────────────────────────
    global_stats = _compute_summary([pos for pos, _ in rows])

    # ── Stats por bot ─────────────────────────────────────────
    bots_map: dict[uuid.UUID, list[Position]] = {}
    for pos, bot in rows:
        bots_map.setdefault(bot.id, []).append(pos)

    # Añadir bots sin trades (para que aparezcan en la lista)
    all_bots_result = await db.execute(
        select(BotConfig).where(BotConfig.user_id == user_id)
    )
    all_bots = {b.id: b for b in all_bots_result.scalars()}

    by_bot: list[BotStats] = []
    for bot_id, positions in bots_map.items():
        bot = all_bots[bot_id]
        stats = _compute_summary(positions)
        by_bot.append(BotStats(
            bot_id=bot.id,
            bot_name=bot.bot_name,
            symbol=bot.symbol,
            status=bot.status,
            total_trades=stats.total_trades,
            winning_trades=stats.winning_trades,
            win_rate=stats.win_rate,
            total_pnl=stats.total_pnl,
        ))

    # Bots sin trades
    for bot_id, bot in all_bots.items():
        if bot_id not in bots_map:
            by_bot.append(BotStats(
                bot_id=bot.id,
                bot_name=bot.bot_name,
                symbol=bot.symbol,
                status=bot.status,
                total_trades=0,
                winning_trades=0,
                win_rate=0.0,
                total_pnl=Decimal("0"),
            ))

    # ── Curva de equity (PnL acumulado cronológico) ───────────
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
    """Stats de un bot específico."""
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

    if not rows:
        bot_result = await db.execute(
            select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user_id)
        )
        bot = bot_result.scalar_one_or_none()
        return BotStats(
            bot_id=bot.id, bot_name=bot.bot_name, symbol=bot.symbol,
            status=bot.status, total_trades=0, winning_trades=0,
            win_rate=0.0, total_pnl=Decimal("0"),
        )

    positions = [pos for pos, _ in rows]
    bot = rows[0][1]
    stats = _compute_summary(positions)

    return BotStats(
        bot_id=bot.id,
        bot_name=bot.bot_name,
        symbol=bot.symbol,
        status=bot.status,
        total_trades=stats.total_trades,
        winning_trades=stats.winning_trades,
        win_rate=stats.win_rate,
        total_pnl=stats.total_pnl,
    )


@router.get("/symbols")
async def get_traded_symbols(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Devuelve todos los símbolos con trades registrados."""
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
    source:    str | None  = Query(None, description="'manual', 'bots', o None para todos"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """PnL diario + acumulado desde exchange_trades (datos reales de BingX)."""
    day_col = cast(ExchangeTrade.closed_at, Date).label("day")

    query = (
        select(day_col, func.sum(func.coalesce(ExchangeTrade.realized_pnl, 0)).label("daily_pnl"))
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
        ))
    return points


# ─── Helpers ─────────────────────────────────────────────────

def _compute_summary(positions: list[Position]) -> TradeSummary:
    if not positions:
        return TradeSummary(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0.0, total_pnl=Decimal("0"), average_pnl=Decimal("0"),
            best_trade=Decimal("0"), worst_trade=Decimal("0"),
        )

    pnls = [p.realized_pnl for p in positions if p.realized_pnl is not None]
    total = len(pnls)
    if total == 0:
        return TradeSummary(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0.0, total_pnl=Decimal("0"), average_pnl=Decimal("0"),
            best_trade=Decimal("0"), worst_trade=Decimal("0"),
        )

    wins = sum(1 for p in pnls if p > 0)

    return TradeSummary(
        total_trades=total,
        winning_trades=wins,
        losing_trades=total - wins,
        win_rate=round(wins / total, 4),
        total_pnl=sum(pnls, Decimal("0")),
        average_pnl=sum(pnls, Decimal("0")) / total,
        best_trade=max(pnls),
        worst_trade=min(pnls),
    )
