"""
Tareas Celery para auto-optimización automática de bots.
Se ejecuta periódicamente (cada 5 min) y también tras cerrar una posición.
"""
import asyncio
import uuid

from celery import shared_task
from loguru import logger
from sqlalchemy import select

from app.models.bot_config import BotConfig
from app.services.cache import publish_notification_sync
from app.services.database import AsyncSessionLocal


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _auto_optimize_bot(bot_id: uuid.UUID):
    """Ejecuta auto-optimize para un bot específico."""
    async with AsyncSessionLocal() as db:
        try:
            # Importar aquí para evitar circular imports
            from app.api.routes.optimizer import _run_auto_optimize_for_bot

            bot_result = await db.execute(
                select(BotConfig).where(BotConfig.id == bot_id)
            )
            bot = bot_result.scalar_one_or_none()
            if not bot or not bot.auto_optimize_enabled:
                return {"status": "skipped", "reason": "not_enabled"}

            result = await _run_auto_optimize_for_bot(bot, db, dry_run=False)
            logger.info(f"[AUTO-OPTIMIZE TASK] Bot {bot_id}: {result['status']}")
            
            # Notificar si se aplicaron cambios
            if result.get("status") == "applied" and result.get("changes"):
                try:
                    from app.tasks.notification_tasks import auto_optimized
                    auto_optimized.delay(
                        bot_name=bot.bot_name,
                        symbol=bot.symbol,
                        changes=result["changes"],
                        health_score=result.get("health_score", 0),
                        crisis_mode=result.get("crisis_mode", False),
                    )
                    # Notificación in-app vía WebSocket
                    changes_str = ", ".join(
                        f"{k}: {v}" for k, v in result["changes"].items()
                    )
                    publish_notification_sync(
                        str(bot.user_id),
                        {
                            "notification_type": "optimizer",
                            "title": f"Auto-optimizacion: {bot.bot_name}",
                            "message": f"Cambios: {changes_str}. Salud: {result.get('health_score', 0)}/100",
                        }
                    )
                except Exception as ne:
                    logger.warning(f"[AUTO-OPTIMIZE TASK] No se pudo enviar notificacion: {ne}")
            
            return result
        except Exception as e:
            logger.error(f"[AUTO-OPTIMIZE TASK] Error en bot {bot_id}: {e}")
            return {"status": "error", "message": str(e)}


@shared_task(
    bind=True,
    max_retries=2,
    name="app.tasks.optimizer_tasks.auto_optimize_bot_task",
    queue="default",
)
def auto_optimize_bot_task(self, bot_id: str):
    """
    Ejecuta auto-optimize para un bot específico.
    Se dispara tras cerrar una posición o manualmente.
    """
    logger.info(f"[AUTO-OPTIMIZE TASK] Iniciando para bot {bot_id}")
    try:
        result = _run_async(_auto_optimize_bot(uuid.UUID(bot_id)))
        return result
    except Exception as exc:
        logger.error(f"[AUTO-OPTIMIZE TASK] Error: {exc}")
        raise self.retry(exc=exc, countdown=60)


@shared_task(
    bind=True,
    max_retries=2,
    name="app.tasks.optimizer_tasks.auto_optimize_all_bots_task",
    queue="default",
)
def auto_optimize_all_bots_task(self):
    """
    Recorre TODOS los bots con auto-optimize habilitado y ejecuta evaluación.
    Se dispara periódicamente vía Celery Beat.
    """
    logger.info("[AUTO-OPTIMIZE TASK] Evaluando todos los bots habilitados...")

    async def _evaluate_all():
        results = []
        async with AsyncSessionLocal() as db:
            bots_result = await db.execute(
                select(BotConfig).where(BotConfig.auto_optimize_enabled == True)
            )
            bots = bots_result.scalars().all()

            if not bots:
                logger.info("[AUTO-OPTIMIZE TASK] No hay bots con auto-optimize habilitado")
                return results

            from app.api.routes.optimizer import _run_auto_optimize_for_bot

            for bot in bots:
                try:
                    result = await _run_auto_optimize_for_bot(bot, db, dry_run=False)
                    results.append({
                        "bot_id": str(bot.id),
                        "bot_name": bot.bot_name,
                        "status": result.get("status"),
                        "changes": result.get("changes"),
                    })
                    logger.info(
                        f"[AUTO-OPTIMIZE TASK] {bot.bot_name}: {result['status']}"
                    )
                    
                    # Notificar si se aplicaron cambios
                    if result.get("status") == "applied" and result.get("changes"):
                        try:
                            from app.tasks.notification_tasks import auto_optimized
                            auto_optimized.delay(
                                bot_name=bot.bot_name,
                                symbol=bot.symbol,
                                changes=result["changes"],
                                health_score=result.get("health_score", 0),
                                crisis_mode=result.get("crisis_mode", False),
                            )
                            # Notificación in-app vía WebSocket
                            changes_str = ", ".join(
                                f"{k}: {v}" for k, v in result["changes"].items()
                            )
                            publish_notification_sync(
                                str(bot.user_id),
                                {
                                    "notification_type": "optimizer",
                                    "title": f"Auto-optimizacion: {bot.bot_name}",
                                    "message": f"Cambios: {changes_str}. Salud: {result.get('health_score', 0)}/100",
                                }
                            )
                        except Exception as ne:
                            logger.warning(f"[AUTO-OPTIMIZE TASK] No se pudo enviar notificacion: {ne}")
                except Exception as e:
                    logger.error(
                        f"[AUTO-OPTIMIZE TASK] Error en {bot.bot_name}: {e}"
                    )
                    results.append({
                        "bot_id": str(bot.id),
                        "bot_name": bot.bot_name,
                        "status": "error",
                        "message": str(e),
                    })
            await db.commit()
        return results

    try:
        return _run_async(_evaluate_all())
    except Exception as exc:
        logger.error(f"[AUTO-OPTIMIZE TASK] Error general: {exc}")
        raise self.retry(exc=exc, countdown=120)
