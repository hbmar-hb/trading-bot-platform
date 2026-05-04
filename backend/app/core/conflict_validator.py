"""
Valida que no haya conflictos de símbolo antes de activar un bot
o antes de ejecutar una orden.

Regla: un único bot activo por símbolo + cuenta de exchange.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot_config import BotConfig
from app.models.position import Position


async def has_active_bot_conflict(
    db: AsyncSession,
    symbol: str,
    exchange_account_id: uuid.UUID,
    exclude_bot_id: uuid.UUID | None = None,
) -> BotConfig | None:
    """
    Devuelve el bot conflictivo (activo, mismo símbolo + cuenta) o None.
    exclude_bot_id: ignorar el propio bot al comprobar (usado al activar).
    
    NOTA: Los bots con prefijo [MANUAL] no bloquean otros bots, ya que son
    posiciones manuales abiertas desde la app, no bots de trading automático.
    """
    from sqlalchemy import not_
    
    query = select(BotConfig).where(
        BotConfig.symbol == symbol,
        BotConfig.exchange_account_id == exchange_account_id,
        BotConfig.status == "active",
        # Ignorar bots manuales (no bloquean otros bots)
        not_(BotConfig.bot_name.startswith("[MANUAL]")),
    )
    if exclude_bot_id:
        query = query.where(BotConfig.id != exclude_bot_id)

    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none()


async def has_open_position(
    db: AsyncSession,
    symbol: str,
    exchange_account_id: uuid.UUID,
    exclude_bot_id: uuid.UUID | None = None,
) -> Position | None:
    """
    Devuelve la posición abierta para este símbolo + cuenta, o None.
    Permite que el propio bot tenga una posición (exclude_bot_id).
    """
    query = (
        select(Position)
        .join(BotConfig, Position.bot_id == BotConfig.id)
        .where(
            Position.symbol == symbol,
            BotConfig.exchange_account_id == exchange_account_id,
            Position.status == "open",
        )
    )
    if exclude_bot_id:
        query = query.where(Position.bot_id != exclude_bot_id)

    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none()
