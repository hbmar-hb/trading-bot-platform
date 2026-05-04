"""
Endpoints para gestionar cuentas de Paper Trading.

Las cuentas paper permiten simular operaciones sin usar dinero real.
Cada usuario puede tener múltiples cuentas paper con diferentes balances iniciales.
"""
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id
from app.models.paper_balance import PaperBalance
from app.schemas.paper_trading import (
    PaperBalanceCreate,
    PaperBalanceResponse,
    PaperBalanceUpdate,
)
from app.services.database import get_db

router = APIRouter(prefix="/paper-trading", tags=["paper-trading"])


async def _get_balance_or_404(
    balance_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> PaperBalance:
    """Obtiene una cuenta paper o lanza 404."""
    result = await db.execute(
        select(PaperBalance).where(
            PaperBalance.id == balance_id,
            PaperBalance.user_id == user_id,
        )
    )
    balance = result.scalar_one_or_none()
    if not balance:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta paper no encontrada")
    return balance


@router.get("/", response_model=list[PaperBalanceResponse])
async def list_paper_accounts(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Lista todas las cuentas paper del usuario."""
    result = await db.execute(
        select(PaperBalance)
        .where(PaperBalance.user_id == user_id)
        .order_by(PaperBalance.created_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=PaperBalanceResponse, status_code=status.HTTP_201_CREATED)
async def create_paper_account(
    data: PaperBalanceCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Crea una nueva cuenta de Paper Trading.
    
    El balance inicial por defecto es 10,000 USDT.
    """
    # Generar account_id único
    account_id = f"paper_{user_id}_{uuid.uuid4().hex[:8]}"
    
    balance = PaperBalance(
        user_id=user_id,
        account_id=account_id,
        label=data.label,
        initial_balance=data.initial_balance,
        available_balance=data.initial_balance,
        total_equity=data.initial_balance,
    )
    
    db.add(balance)
    await db.commit()
    await db.refresh(balance)
    
    return balance


@router.get("/{balance_id}", response_model=PaperBalanceResponse)
async def get_paper_account(
    balance_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Obtiene detalles de una cuenta paper específica."""
    return await _get_balance_or_404(balance_id, user_id, db)


@router.patch("/{balance_id}", response_model=PaperBalanceResponse)
async def update_paper_account(
    balance_id: uuid.UUID,
    data: PaperBalanceUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Actualiza el label de una cuenta paper."""
    balance = await _get_balance_or_404(balance_id, user_id, db)
    
    if data.label is not None:
        balance.label = data.label
    
    await db.commit()
    await db.refresh(balance)
    return balance


@router.post("/{balance_id}/reset", response_model=PaperBalanceResponse)
async def reset_paper_account(
    balance_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Resetea el balance de la cuenta paper al valor inicial.
    Útil para empezar de nuevo sin crear una cuenta nueva.
    """
    balance = await _get_balance_or_404(balance_id, user_id, db)
    
    balance.reset_balance()
    await db.commit()
    await db.refresh(balance)
    
    return balance


@router.delete("/{balance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paper_account(
    balance_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Elimina una cuenta paper y todas sus posiciones simuladas."""
    balance = await _get_balance_or_404(balance_id, user_id, db)
    
    # TODO: Opcionalmente eliminar posiciones abiertas asociadas
    
    await db.delete(balance)
    await db.commit()


@router.get("/{balance_id}/balance", response_model=dict)
async def get_balance(
    balance_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Obtiene el balance actual calculado (con unrealized PnL)."""
    from app.exchanges.paper import PaperExchange
    
    balance = await _get_balance_or_404(balance_id, user_id, db)
    
    # Crear exchange paper para calcular balance actual
    exchange = PaperExchange(
        account_id=balance.account_id,
        initial_balance=balance.initial_balance
    )
    
    try:
        balance_info = await exchange.get_equity()
        return {
            "account_id": balance.account_id,
            "label": balance.label,
            "available_balance": float(balance_info.available_balance),
            "total_equity": float(balance_info.total_equity),
            "unrealized_pnl": float(balance_info.unrealized_pnl),
            "initial_balance": float(balance.initial_balance),
        }
    finally:
        await exchange.close()
