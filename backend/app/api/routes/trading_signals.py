"""Endpoints para gestionar señales de trading"""
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.api.dependencies import get_current_user_id
from app.services.database import get_db
from app.models.trading_signal import TradingSignal
from app.schemas.trading_signal import TradingSignalResponse, TradingSignalList

router = APIRouter(prefix="/trading-signals", tags=["trading-signals"])


@router.get("", response_model=TradingSignalList)
async def list_signals(
    symbol: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Obtener historial de señales de trading."""
    
    query = select(TradingSignal).where(
        TradingSignal.user_id == user_id,
        TradingSignal.received_at >= datetime.utcnow() - timedelta(days=days)
    )
    
    if symbol:
        query = query.where(TradingSignal.symbol == symbol)
    if action:
        query = query.where(TradingSignal.action == action)
    if status:
        query = query.where(TradingSignal.status == status)
    
    # Contar total
    count_query = select(TradingSignal).where(
        TradingSignal.user_id == user_id,
        TradingSignal.received_at >= datetime.utcnow() - timedelta(days=days)
    )
    if symbol:
        count_query = count_query.where(TradingSignal.symbol == symbol)
    if action:
        count_query = count_query.where(TradingSignal.action == action)
    if status:
        count_query = count_query.where(TradingSignal.status == status)
    
    total_result = await db.execute(count_query)
    total = len(total_result.scalars().all())
    
    # Obtener datos paginados
    query = query.order_by(desc(TradingSignal.received_at))
    query = query.offset(offset).limit(limit)
    
    result = await db.execute(query)
    signals = result.scalars().all()
    
    return TradingSignalList(
        total=total,
        signals=[TradingSignalResponse.model_validate(s) for s in signals]
    )


@router.get("/{signal_id}", response_model=TradingSignalResponse)
async def get_signal(
    signal_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Obtener detalle de una señal específica."""
    result = await db.execute(
        select(TradingSignal).where(
            TradingSignal.id == signal_id,
            TradingSignal.user_id == user_id
        )
    )
    signal = result.scalar_one_or_none()
    
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    
    return TradingSignalResponse.model_validate(signal)


@router.get("/stats/summary")
async def get_signals_stats(
    days: int = Query(default=7, ge=1, le=90),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Estadísticas de señales recibidas."""
    from sqlalchemy import func
    
    query = select(
        TradingSignal.action,
        func.count().label('count'),
        func.avg(TradingSignal.price).label('avg_price')
    ).where(
        TradingSignal.user_id == user_id,
        TradingSignal.received_at >= datetime.utcnow() - timedelta(days=days)
    ).group_by(TradingSignal.action)
    
    result = await db.execute(query)
    stats = result.all()
    
    return {
        "period_days": days,
        "by_action": [
            {
                "action": row.action,
                "count": row.count,
                "avg_price": float(row.avg_price) if row.avg_price else None
            }
            for row in stats
        ]
    }


from fastapi import HTTPException
