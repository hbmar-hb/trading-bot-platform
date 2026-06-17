import asyncio
from datetime import datetime, timezone

from celery import shared_task
from loguru import logger
from sqlalchemy import select, update as sa_update, not_

from app.exchanges.factory import create_exchange
from app.models.bot_config import BotConfig
from app.models.exchange_account import ExchangeAccount
from app.services.cache import set_exchange_health_sync
from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
from app.services.autonomy_state import mark_paused, clear_pause


@shared_task(name="app.tasks.health_check_tasks.check_exchanges")
def check_exchanges() -> dict:
    """
    Verifica conectividad y validez de credenciales para todas las cuentas
    de exchange que tienen bots activos. Almacena resultados en la DB.

    AUTONOMOUS BEHAVIOUR:
      - Pauses bots on accounts with credential/network errors.
      - Auto-resumes bots when the account recovers to healthy.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(_run_checks())


async def _run_checks() -> dict:
    """Ejecuta health checks de credenciales para todas las cuentas activas."""
    results = {}
    paused = 0
    resumed = 0

    async with AsyncSessionLocal() as db:
        # Obtener cuentas que tienen bots activos o pausados por exchange_health
        result = await db.execute(
            select(ExchangeAccount)
            .join(BotConfig, BotConfig.exchange_account_id == ExchangeAccount.id)
            .where(
                (BotConfig.status == "active") |
                (
                    (BotConfig.status == "paused") &
                    (BotConfig.ai_signal_config.contains({"autonomy_state": {"paused_by": "exchange_health"}}))
                )
            )
            .where(ExchangeAccount.is_active == True)
            .distinct()
        )
        accounts = result.scalars().all()

        for account in accounts:
            check_result = await _check_account_credentials(account)
            
            # Actualizar estado en la cuenta
            account.last_health_check_at = datetime.now(timezone.utc)
            account.last_health_status = check_result["status"]
            account.last_health_error = check_result.get("error")
            
            # Guardar en Redis para acceso rápido
            set_exchange_health_sync(
                f"{account.exchange}_{account.id}",
                check_result["status"]
            )
            
            results[str(account.id)] = {
                "exchange": account.exchange,
                "label": account.label,
                **check_result
            }
            
            if check_result["status"] == "healthy":
                logger.debug(f"✓ Credentials OK: {account.exchange}/{account.label}")
                # Auto-unblock bots that were blocked by exchange_health
                bots_to_resume = (
                    await db.execute(
                        select(BotConfig).where(
                            BotConfig.exchange_account_id == account.id,
                            not_(BotConfig.bot_name.like("[MANUAL]%")),
                        )
                    )
                ).scalars().all()
                for bot in bots_to_resume:
                    cfg = bot.ai_signal_config or {}
                    autonomy = cfg.get("autonomy_state", {})
                    if clear_pause(autonomy, "exchange_health"):
                        cfg.pop("execution_blocked", None)
                        cfg.pop("execution_blocked_reason", None)
                        cfg["autonomy_state"] = autonomy
                        bot.ai_signal_config = cfg
                        resumed += 1
                        logger.info(
                            f"[HEALTH CHECK] Auto-unblocked bot {bot.bot_name} — "
                            f"exchange {account.label} recovered"
                        )
            else:
                logger.warning(
                    f"✗ Credentials FAIL: {account.exchange}/{account.label} — "
                    f"{check_result.get('error', 'Unknown error')}"
                )
                # Auto-block bots on broken exchange
                bots_to_block = (
                    await db.execute(
                        select(BotConfig).where(
                            BotConfig.exchange_account_id == account.id,
                            BotConfig.status == "active",
                            not_(BotConfig.bot_name.like("[MANUAL]%")),
                        )
                    )
                ).scalars().all()
                for bot in bots_to_block:
                    cfg = bot.ai_signal_config or {}
                    autonomy = cfg.get("autonomy_state", {})
                    if mark_paused(autonomy, "exchange_health"):
                        cfg["execution_blocked"] = True
                        cfg["execution_blocked_reason"] = "exchange_health"
                        cfg["autonomy_state"] = autonomy
                        bot.ai_signal_config = cfg
                        paused += 1
                    logger.warning(
                        f"[HEALTH CHECK] Auto-blocked bot {bot.bot_name} — "
                        f"exchange {account.label} {check_result['status']}"
                    )
        
        if paused or resumed:
            await db.commit()

    return {
        "results": results,
        "paused_bots": paused,
        "resumed_bots": resumed,
    }


async def _check_account_credentials(account: ExchangeAccount) -> dict:
    """
    Verifica las credenciales de una cuenta específica.
    Intenta hacer una operación que requiere autenticación (get_equity).
    """
    exchange = create_exchange(account)
    try:
        # Intentar obtener balance - esto requiere credenciales válidas
        await exchange.get_equity()
        return {
            "status": "healthy",
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as exc:
        error_str = str(exc).lower()
        
        # Clasificar el tipo de error
        if any(x in error_str for x in ["apikey", "api key", "key", "secret", "unauthorized", "authentication", "auth"]):
            status = "error_credentials"
        elif any(x in error_str for x in ["network", "timeout", "connection", "dns", "unable to connect"]):
            status = "error_network"
        else:
            status = "error_unknown"
        
        return {
            "status": status,
            "error": str(exc)[:500],
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    finally:
        await exchange.close()


@shared_task(name="app.tasks.health_check_tasks.check_single_account")
def check_single_account(account_id: str) -> dict:
    """
    Verifica las credenciales de una cuenta específica.
    Útil para verificar inmediatamente después de actualizar credenciales.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(_check_single(str(account_id)))


async def _check_single(account_id: str) -> dict:
    """Verifica una cuenta específica por ID."""
    import uuid
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ExchangeAccount).where(ExchangeAccount.id == uuid.UUID(account_id))
        )
        account = result.scalar_one_or_none()
        
        if not account:
            return {"status": "error", "error": "Account not found"}
        
        check_result = await _check_account_credentials(account)
        
        # Actualizar estado
        account.last_health_check_at = datetime.now(timezone.utc)
        account.last_health_status = check_result["status"]
        account.last_health_error = check_result.get("error")
        
        set_exchange_health_sync(
            f"{account.exchange}_{account.id}",
            check_result["status"]
        )
        
        await db.commit()
        
        return {
            "account_id": account_id,
            "exchange": account.exchange,
            "label": account.label,
            **check_result
        }
