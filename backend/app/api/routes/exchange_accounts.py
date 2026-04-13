import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id
from app.exchanges.factory import create_exchange
from app.models.exchange_account import ExchangeAccount
from app.schemas.exchange_account import (
    ExchangeAccountCreate,
    ExchangeAccountResponse,
    ExchangeAccountTestResponse,
    ExchangeAccountUpdate,
)
from app.services.database import get_db
from app.utils.crypto import encrypt

router = APIRouter(prefix="/exchange-accounts", tags=["exchange-accounts"])


# ── Helpers ───────────────────────────────────────────────────

async def _get_account_or_404(
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> ExchangeAccount:
    result = await db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.id == account_id,
            ExchangeAccount.user_id == user_id,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cuenta de exchange no encontrada")
    return account


# ── Endpoints ─────────────────────────────────────────────────

@router.get("", response_model=list[ExchangeAccountResponse])
async def list_accounts(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.user_id == user_id)
        .order_by(ExchangeAccount.created_at)
    )
    return result.scalars().all()


@router.post("", response_model=ExchangeAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    data: ExchangeAccountCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    account = ExchangeAccount(
        user_id=user_id,
        exchange=data.exchange,
        label=data.label,
        api_key_encrypted=encrypt(data.api_key),
        secret_encrypted=encrypt(data.secret),
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@router.get("/{account_id}", response_model=ExchangeAccountResponse)
async def get_account(
    account_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await _get_account_or_404(account_id, user_id, db)


@router.patch("/{account_id}", response_model=ExchangeAccountResponse)
async def update_account(
    account_id: uuid.UUID,
    data: ExchangeAccountUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    account = await _get_account_or_404(account_id, user_id, db)

    if data.label is not None:
        account.label = data.label
    if data.is_active is not None:
        account.is_active = data.is_active
    
    # Actualizar credenciales si se proporcionan
    if data.api_key is not None:
        account.api_key_encrypted = encrypt(data.api_key)
    if data.secret is not None:
        account.secret_encrypted = encrypt(data.secret)

    await db.commit()
    await db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    account = await _get_account_or_404(account_id, user_id, db)

    # Verificar que no haya bots activos usando esta cuenta
    from app.models.bot_config import BotConfig
    bots_result = await db.execute(
        select(BotConfig).where(
            BotConfig.exchange_account_id == account_id,
            BotConfig.status == "active",
        ).limit(1)
    )
    if bots_result.scalar_one_or_none():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No se puede eliminar: hay bots activos usando esta cuenta. "
            "Pausa o desactiva los bots primero.",
        )

    await db.delete(account)
    await db.commit()


@router.get("/{account_id}/markets", response_model=list[str])
async def get_markets(
    account_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Devuelve los símbolos de futuros perpetuos disponibles en el exchange."""
    account = await _get_account_or_404(account_id, user_id, db)
    exchange = create_exchange(account)
    try:
        return await exchange.get_markets()
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Error al obtener mercados: {e}")
    finally:
        await exchange.close()


@router.get("/markets-by-exchange/{exchange_name}", response_model=list[str])
async def get_markets_by_exchange(
    exchange_name: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Devuelve los símbolos de futuros perpetuos disponibles en un exchange
    sin necesidad de tener una cuenta configurada. Útil para paper trading.
    """
    import ccxt.async_support as ccxt
    
    try:
        # Crear instancia del exchange sin credenciales
        exchange_class = getattr(ccxt, exchange_name.lower(), None)
        if not exchange_class:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, 
                f"Exchange no soportado: {exchange_name}"
            )
        
        exchange = exchange_class({'enableRateLimit': True})
        
        # Cargar mercados
        markets = await exchange.load_markets()
        
        # Filtrar solo futuros perpetuos (swap)
        perpetuals = [
            symbol for symbol, market in markets.items()
            if market.get('swap') and market.get('linear')  # Futuros perpetuos lineales (USDT margined)
        ]
        
        await exchange.close()
        
        # Ordenar y limitar
        return sorted(perpetuals)[:500]
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, 
            f"Error al obtener mercados de {exchange_name}: {e}"
        )


async def _check_credentials_sync(account: ExchangeAccount) -> dict:
    """Verifica las credenciales de forma síncrona (para usar en endpoints async)."""
    exchange = None
    try:
        from app.exchanges.factory import create_exchange
        from app.exchanges.bitunix import BitunixExchange

        exchange = create_exchange(account)

        # Para Bitunix, usar el método de verificación dedicado
        if isinstance(exchange, BitunixExchange):
            verify_result = await exchange.verify_credentials()
            if verify_result.get("success"):
                return {"status": "healthy", "error": None, "details": verify_result}
            return {
                "status": "error_credentials",
                "error": verify_result.get("error", "Autenticación fallida"),
            }

        # Para otros exchanges, obtener balance
        await exchange.get_equity()
        return {"status": "healthy", "error": None}

    except Exception as exc:
        from loguru import logger
        logger.exception(f"[verify_credentials] account={account.id} exchange={account.exchange}: {exc}")
        error_str = str(exc).lower()
        if any(x in error_str for x in ["apikey", "api key", "key", "secret", "unauthorized", "authentication", "auth", "forbidden", "403", "401"]):
            err_status = "error_credentials"
        elif any(x in error_str for x in ["network", "timeout", "connection", "dns", "unable to connect"]):
            err_status = "error_network"
        else:
            err_status = "error_unknown"
        return {"status": err_status, "error": str(exc)[:500]}

    finally:
        if exchange is not None:
            try:
                await exchange.close()
            except Exception:
                pass


def _get_status_message(status: str, error: str | None) -> str:
    """Devuelve un mensaje descriptivo del estado de las credenciales."""
    messages = {
        "healthy": "✓ Credenciales válidas y funcionando correctamente",
        "error_credentials": f"✗ Error de credenciales: {error or 'API Key o Secret inválidos'}",
        "error_network": f"✗ Error de red: {error or 'No se pudo conectar al exchange'}",
        "error_unknown": f"✗ Error desconocido: {error or 'Verificación fallida'}",
    }
    return messages.get(status, f"✗ Estado desconocido: {status}")


@router.get("/{account_id}/balance")
async def get_account_balance(
    account_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Devuelve equity y balance disponible de una cuenta de exchange."""
    account = await _get_account_or_404(account_id, user_id, db)
    exchange = create_exchange(account)
    try:
        info = await exchange.get_equity()
        return {
            "account_id": str(account_id),
            "total_equity": float(info.total_equity),
            "available_balance": float(info.available_balance),
        }
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Error al obtener balance: {exc}")
    finally:
        await exchange.close()


@router.get("/balance/all")
async def get_all_balances(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Devuelve equity de todas las cuentas activas del usuario."""
    import asyncio
    result = await db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.user_id == user_id,
            ExchangeAccount.is_active == True,
        )
    )
    accounts = result.scalars().all()

    async def fetch_one(account):
        exchange = create_exchange(account)
        try:
            info = await exchange.get_equity()
            return {
                "account_id": str(account.id),
                "label": account.label,
                "exchange": account.exchange,
                "total_equity": float(info.total_equity),
                "available_balance": float(info.available_balance),
                "error": None,
            }
        except Exception as exc:
            return {
                "account_id": str(account.id),
                "label": account.label,
                "exchange": account.exchange,
                "total_equity": 0.0,
                "available_balance": 0.0,
                "error": str(exc)[:200],
            }
        finally:
            await exchange.close()

    results = await asyncio.gather(*[fetch_one(a) for a in accounts])
    return {"accounts": results}


@router.post("/{account_id}/test", response_model=ExchangeAccountTestResponse)
async def test_account(
    account_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Verifica la conectividad y validez de las credenciales con el exchange."""
    from datetime import datetime, timezone
    
    account = await _get_account_or_404(account_id, user_id, db)
    
    # Ejecutar verificación de credenciales directamente
    result = await _check_credentials_sync(account)
    
    # Actualizar estado en la cuenta
    account.last_health_check_at = datetime.now(timezone.utc)
    account.last_health_status = result["status"]
    account.last_health_error = result.get("error")
    await db.commit()
    
    is_healthy = result.get("status") == "healthy"
    
    return ExchangeAccountTestResponse(
        exchange=account.exchange,
        label=account.label,
        status="healthy" if is_healthy else "error",
        latency_ms=None,
        error=result.get("error") if not is_healthy else None,
    )


@router.post("/{account_id}/verify-credentials")
async def verify_credentials(
    account_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Fuerza una verificación inmediata de las credenciales y devuelve el resultado detallado.
    Actualiza el estado en la base de datos.
    """
    from datetime import datetime, timezone

    account = await _get_account_or_404(account_id, user_id, db)

    try:
        result = await _check_credentials_sync(account)
    except Exception as exc:
        from loguru import logger
        logger.exception(f"[verify-credentials] unhandled: {exc}")
        result = {"status": "error_unknown", "error": str(exc)[:500]}

    account.last_health_check_at = datetime.now(timezone.utc)
    account.last_health_status = result.get("status", "error_unknown")
    # Truncar a 490 chars para no exceder el VARCHAR(500) de la columna
    raw_error = result.get("error") or ""
    account.last_health_error = raw_error[:490] if raw_error else None
    await db.commit()

    status_val = result.get("status", "error_unknown")
    return {
        "account_id": str(account_id),
        "exchange": account.exchange,
        "label": account.label,
        "status": status_val,
        "is_valid": status_val == "healthy",
        "last_check": account.last_health_check_at.isoformat(),
        "error": result.get("error"),
        "message": _get_status_message(status_val, result.get("error")),
    }
