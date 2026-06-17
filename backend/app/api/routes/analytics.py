import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, cast, Date, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_authorized_user, get_current_user_id
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
from app.schemas.exchange_trade import TradeDetailResponse
from app.services.database import get_db
from app.services.unified_pnl_service import (
    UnifiedTrade,
    build_daily_pnl_curve,
    compute_summary_from_unified,
    get_closed_trades_unified,
)

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(get_current_authorized_user)])


def _apply_source_filter(query, source: str | None):
    """
    Aplica filtro de source a una query de ExchangeTrade.
    source='ai_bot' es EXACTO: solo trades con source='ai_bot' real.

    Por defecto (source=None) excluye source='manual' para evitar que
    trades de estrategias externas (copy trading, grid bots del exchange)
    o la importación masiva histórica contaminen los analytics de la plataforma.
    Para ver solo trades manuales, pasar source='manual' explícitamente.
    """
    if source == "paper":
        return query.join(BotConfig, ExchangeTrade.bot_id == BotConfig.id).where(
            BotConfig.paper_balance_id.is_not(None)
        )
    if source:
        return query.where(ExchangeTrade.source == source)
    # Default: exclude exchange-synced unmatched trades
    return query.where(ExchangeTrade.source != "manual")


@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def get_summary(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
    source: str | None = Query(None, regex="^(bot|bot_int|bot_ext|ai_bot|app_manual|paper|manual)$"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Estadísticas globales + por bot + curva de equity.

    Usa el servicio de PnL unificado: ExchangeTrade para trades reales y
    Position para trades en paper, evitando doble conteo.
    """
    exclude_sources = None
    source_filter = source
    mode = "total"
    if source is None:
        # Default analytics view: exclude manually-imported exchange trades
        exclude_sources = ["manual"]
    elif source == "paper":
        source_filter = None
        mode = "paper"

    trades = await get_closed_trades_unified(
        db,
        user_id=user_id,
        bot_id=bot_id,
        source=source_filter,
        exclude_sources=exclude_sources,
        from_date=from_date,
        to_date=to_date,
        mode=mode,
        order_desc=False,
    )

    # Estadísticas globales
    global_stats = compute_summary_from_unified(trades)

    # ── Stats por bot ─────────────────────────────────────────
    trades_by_bot: dict[uuid.UUID, list[UnifiedTrade]] = {}
    for trade in trades:
        if trade.bot_id:
            trades_by_bot.setdefault(trade.bot_id, []).append(trade)

    # Cargar todos los bots del usuario (excluyendo manuales)
    all_bots_result = await db.execute(
        select(BotConfig).where(
            BotConfig.user_id == user_id,
            ~BotConfig.bot_name.like("[MANUAL]%"),
        )
    )
    all_bots = {b.id: b for b in all_bots_result.scalars()}

    by_bot: list[BotStats] = []
    for bot_id_key, bot in all_bots.items():
        bot_trades = trades_by_bot.get(bot_id_key, [])
        if bot_trades:
            stats = compute_summary_from_unified(bot_trades)
        else:
            zero = Decimal("0")
            stats = TradeSummary(
                total_trades=0, winning_trades=0, losing_trades=0,
                win_rate=0.0, profit_factor=None, total_pnl=zero,
                average_pnl=zero, best_trade=zero, worst_trade=zero,
                max_drawdown=zero, avg_duration_hours=0.0, current_streak=0,
                long_trades=0, short_trades=0, long_win_rate=0.0,
                short_win_rate=0.0, long_pnl=zero, short_pnl=zero,
            )

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

    # Ordenar: más trades primero
    by_bot.sort(key=lambda b: b.total_trades, reverse=True)

    # ── Curva de equity ───────────────────────────────────────
    equity_curve: list[EquityPoint] = []
    cumulative = Decimal("0")
    for trade in trades:
        if trade.closed_at:
            cumulative += trade.realized_pnl
            equity_curve.append(EquityPoint(
                timestamp=trade.closed_at,
                cumulative_pnl=cumulative,
                trade_pnl=trade.realized_pnl,
                symbol=trade.symbol,
                side=trade.side,
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
    """Stats para un bot usando el PnL unificado (real + paper)."""
    bot_result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user_id)
    )
    bot = bot_result.scalar_one_or_none()
    if not bot:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Bot not found")

    trades = await get_closed_trades_unified(
        db,
        user_id=user_id,
        bot_id=bot_id,
        mode="total",
        order_desc=False,
    )
    stats = compute_summary_from_unified(trades)

    return BotStats(
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
    """PnL diario + acumulado desde fuente unificada (real + paper)."""
    exclude_sources = None
    source_filter = source
    mode = "total"
    if source is None:
        exclude_sources = ["manual"]
    elif source == "paper":
        source_filter = None
        mode = "paper"

    trades = await get_closed_trades_unified(
        db,
        user_id=user_id,
        bot_id=bot_id,
        symbol=symbol,
        source=source_filter,
        exclude_sources=exclude_sources,
        from_date=from_date,
        to_date=to_date,
        mode=mode,
        order_desc=False,
    )

    curve = build_daily_pnl_curve(trades)
    cumulative = Decimal("0")
    points: list[DailyPnlPoint] = []
    for row in curve:
        cumulative = row["cumulative_pnl"]
        points.append(DailyPnlPoint(
            date=row["date"],
            daily_pnl=row["daily_pnl"],
            cumulative_pnl=cumulative,
            trade_count=row["trade_count"],
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
    trades = await get_closed_trades_unified(
        db,
        user_id=user_id,
        bot_id=bot_id,
        exclude_sources=["manual"],
        from_date=from_date,
        to_date=to_date,
        mode="total",
        order_desc=False,
    )

    daily: dict[str, dict] = {}
    for t in trades:
        if not t.closed_at:
            continue
        ds = t.closed_at.strftime("%Y-%m-%d")
        cell = daily.setdefault(ds, {"count": 0, "pnl": Decimal("0")})
        cell["count"] += 1
        cell["pnl"] += t.realized_pnl

    return [
        ActivityPoint(
            date=ds,
            count=data["count"],
            pnl=data["pnl"],
        )
        for ds, data in sorted(daily.items())
    ]


@router.get("/hourly-distribution", response_model=list[HourlyStats])
async def get_hourly_distribution(
    from_date: date | None = Query(None),
    to_date:   date | None = Query(None),
    bot_id:    uuid.UUID | None = Query(None),
    symbol:    str | None = Query(None),
    source:    str | None = Query(None),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Distribución de trades por hora del día (0-23)."""
    exclude_sources = None
    source_filter = source
    mode = "total"
    if source is None:
        exclude_sources = ["manual"]
    elif source == "paper":
        source_filter = None
        mode = "paper"

    trades = await get_closed_trades_unified(
        db,
        user_id=user_id,
        bot_id=bot_id,
        symbol=symbol,
        source=source_filter,
        exclude_sources=exclude_sources,
        from_date=from_date,
        to_date=to_date,
        mode=mode,
        order_desc=False,
    )

    hourly: dict[int, dict] = {}
    for t in trades:
        if not t.closed_at:
            continue
        hour = t.closed_at.hour
        cell = hourly.setdefault(hour, {"trades": 0, "wins": 0, "pnl": Decimal("0")})
        cell["trades"] += 1
        cell["pnl"] += t.realized_pnl
        if t.realized_pnl > 0:
            cell["wins"] += 1

    return [
        HourlyStats(
            hour=hour,
            trades=data["trades"],
            wins=data["wins"],
            pnl=data["pnl"],
            win_rate=round(data["wins"] / data["trades"], 4) if data["trades"] > 0 else 0.0,
        )
        for hour, data in sorted(hourly.items())
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


def _compute_summary_from_trades(trades: list) -> TradeSummary:
    """
    Calcula estadísticas desde una lista de ExchangeTrade.
    Versión simplificada de _compute_summary para trades del exchange.
    """
    zero = Decimal("0")
    
    if not trades:
        return TradeSummary(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0.0, profit_factor=None, total_pnl=zero,
            average_pnl=zero, best_trade=zero, worst_trade=zero,
            max_drawdown=zero, avg_duration_hours=0.0, current_streak=0,
            long_trades=0, short_trades=0, long_win_rate=0.0,
            short_win_rate=0.0, long_pnl=zero, short_pnl=zero,
        )
    
    pnls = [t.realized_pnl for t in trades if t.realized_pnl is not None]
    total = len(pnls)
    if total == 0:
        return _compute_summary_from_trades([])
    
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n_wins = len(wins)
    
    total_win = sum(wins, zero)
    total_loss = abs(sum(losses, zero))
    profit_factor = round(float(total_win / total_loss), 2) if total_loss > 0 else None
    
    # Max drawdown
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
    
    # Racha actual
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
    
    # Duración media (disponible en exchange_trades)
    durations = []
    for t in trades:
        if t.opened_at and t.closed_at:
            durations.append((t.closed_at - t.opened_at).total_seconds() / 3600)
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

    # Long vs Short
    longs = [t for t in trades if t.side == "long" and t.realized_pnl is not None]
    shorts = [t for t in trades if t.side == "short" and t.realized_pnl is not None]

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


@router.get("/trades-detail", response_model=list[TradeDetailResponse])
async def get_trades_detail(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    bot_id: uuid.UUID | None = Query(None),
    symbol: str | None = Query(None),
    source: str | None = Query(None, regex="^(bot|bot_int|bot_ext|ai_bot|app_manual|paper|manual)$"),
    limit: int = Query(100, ge=1, le=500),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Obtiene el detalle completo de trades con métricas calculadas.
    
    Incluye ROI, razón de cierre, y datos de la posición asociada.
    """
    from app.models.bot_config import BotConfig
    from app.schemas.exchange_trade import TradeDetailResponse
    
    # Query base con joins a posición y bot
    query = (
        select(ExchangeTrade, Position, BotConfig)
        .outerjoin(Position, ExchangeTrade.position_id == Position.id)
        .outerjoin(BotConfig, ExchangeTrade.bot_id == BotConfig.id)
        .where(
            ExchangeTrade.user_id == user_id,
            ExchangeTrade.closed_at.is_not(None),
            ExchangeTrade.realized_pnl.is_not(None),
        )
        .order_by(ExchangeTrade.closed_at.desc())
    )
    
    # Aplicar filtros
    if from_date:
        query = query.where(cast(ExchangeTrade.closed_at, Date) >= from_date)
    if to_date:
        query = query.where(cast(ExchangeTrade.closed_at, Date) <= to_date)
    if bot_id:
        query = query.where(ExchangeTrade.bot_id == bot_id)
    if symbol:
        query = query.where(ExchangeTrade.symbol == symbol)
    if source == "paper":
        query = query.where(BotConfig.paper_balance_id.is_not(None))
    elif source:
        query = query.where(ExchangeTrade.source == source)
    else:
        query = query.where(ExchangeTrade.source != "manual")

    query = query.limit(limit)
    
    result = await db.execute(query)
    rows = result.all()
    
    trades_detail = []
    for trade, position, bot in rows:
        # Calcular ROI y valor de posición
        roi_percent = None
        position_value = None
        
        if trade.entry_price and trade.quantity and trade.realized_pnl is not None:
            # Valor de la posición = cantidad * precio entrada
            position_value = float(trade.quantity) * float(trade.entry_price)
            
            # ROI = (PnL / Valor posición) * 100 (asumiendo 1x leverage si no tenemos datos)
            leverage = position.leverage if position and position.leverage else 1
            margin = position_value / leverage
            
            if margin > 0:
                roi_percent = (float(trade.realized_pnl) / margin) * 100
        
        # Determinar razón de cierre
        close_reason = _determine_close_reason(trade, position)
        
        trades_detail.append(TradeDetailResponse(
            id=trade.id,
            symbol=trade.symbol,
            side=trade.side,
            source=trade.source,
            quantity=trade.quantity,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            realized_pnl=trade.realized_pnl,
            fee=trade.fee,
            roi_percent=round(roi_percent, 2) if roi_percent is not None else None,
            position_value=round(position_value, 2) if position_value is not None else None,
            close_reason=close_reason,
            bot_id=trade.bot_id,
            bot_name=bot.bot_name if bot else None,
            position_id=trade.position_id,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
        ))
    
    return trades_detail


def _determine_close_reason(trade: ExchangeTrade, position: Position | None) -> str:
    """Determina la razón de cierre basada en los datos del trade y posición."""
    if not trade.exit_price or not position:
        return "Unknown"
    
    exit_price = float(trade.exit_price)
    side = trade.side
    
    # Verificar Stop Loss
    if position.current_sl_price:
        sl_price = float(position.current_sl_price)
        # Para long: si salió por debajo del SL
        # Para short: si salió por encima del SL
        if side == "long" and exit_price <= sl_price * 1.001:  # 0.1% de tolerancia
            return "SL"
        if side == "short" and exit_price >= sl_price * 0.999:
            return "SL"
    
    # Verificar Take Profits
    if position.current_tp_prices and isinstance(position.current_tp_prices, list):
        for tp in position.current_tp_prices:
            if isinstance(tp, dict) and tp.get("price"):
                tp_price = float(tp["price"])
                level = tp.get("level", 1)
                
                if side == "long" and exit_price >= tp_price * 0.999:
                    return f"TP{level}"
                if side == "short" and exit_price <= tp_price * 1.001:
                    return f"TP{level}"
    
    # Verificar Trailing Stop (si está en extra_config)
    if position.extra_config:
        extra = position.extra_config
        if isinstance(extra, dict):
            # Si hay trailing config y el precio no coincide con SL ni TP
            if extra.get("trailing_activated"):
                return "Trailing Stop"
            # Breakeven
            if extra.get("breakeven_activated"):
                entry = float(trade.entry_price) if trade.entry_price else 0
                if abs(exit_price - entry) < entry * 0.001:  # Muy cerca del entry
                    return "Breakeven"
    
    # Si no coincide con ninguno, probablemente fue manual
    return "Manual"
