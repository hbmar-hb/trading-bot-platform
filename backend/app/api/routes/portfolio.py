"""Portfolio Manager endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_authorized_user, require_developer_role
from app.models.bot_config import BotConfig
from app.models.position import Position
from app.services.database import get_db
from app.tasks.kill_switch_task import execute_kill_switch

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _notional(pos: Position) -> float:
    return float(pos.quantity) * float(pos.entry_price)


@router.get("/summary")
async def portfolio_summary(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_authorized_user),
):
    """Return aggregated portfolio exposure for the current user."""
    bots_result = await db.execute(
        select(BotConfig).where(
            BotConfig.user_id == user.id,
            BotConfig.status == "active",
        )
    )
    bots = bots_result.scalars().all()
    bot_ids = [b.id for b in bots]

    positions = []
    if bot_ids:
        pos_result = await db.execute(
            select(Position).where(
                Position.bot_id.in_(bot_ids),
                Position.status == "open",
            )
        )
        positions = pos_result.scalars().all()

    total_long = sum(_notional(p) for p in positions if p.side == "long")
    total_short = sum(_notional(p) for p in positions if p.side == "short")

    by_symbol: dict[str, dict] = {}
    for p in positions:
        s = p.symbol
        if s not in by_symbol:
            by_symbol[s] = {"long": 0.0, "short": 0.0, "net": 0.0}
        n = _notional(p)
        by_symbol[s][p.side] += n
        by_symbol[s]["net"] += n if p.side == "long" else -n

    return {
        "open_count": len(positions),
        "total_long": round(total_long, 2),
        "total_short": round(total_short, 2),
        "net_exposure": round(total_long - total_short, 2),
        "by_symbol": [
            {"symbol": k, **{sk: round(sv, 2) for sk, sv in v.items()}}
            for k, v in by_symbol.items()
        ],
    }


@router.post("/kill-switch", status_code=status.HTTP_202_ACCEPTED)
async def kill_switch(
    db: AsyncSession = Depends(get_db),
    user = Depends(require_developer_role),
):
    """
    Kill switch manual: cierra TODAS las posiciones abiertas del usuario
    a mercado, cancela órdenes pendientes, y pausa todos sus bots.
    La ejecución real ocurre en background vía Celery.
    """
    task = execute_kill_switch.delay(str(user.id))
    return {
        "message": "Kill switch ejecutado",
        "task_id": task.id,
        "user_id": str(user.id),
    }
