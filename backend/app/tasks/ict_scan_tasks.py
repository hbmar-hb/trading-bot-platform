"""
Tarea Celery que ejecuta el motor ICT sobre los bots habilitados para ICT scan.

Ciclo (disparado por Beat cada 60 s):
  1. Obtener todos los bots activos con ict_scan_enabled=True
  2. Por cada bot, comprobar si ha pasado al menos un período de vela desde el
     último escaneo (throttle por timeframe — no escanear más de 1 vez por vela)
  3. Obtener velas del exchange
  4. Ejecutar análisis ICT (excluye la vela en curso para evitar look-ahead)
  5. Si hay señal → crear SignalLog + disparar execute_signal task
"""
import asyncio
from datetime import datetime, timezone

from celery import shared_task
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.services.cache import sync_redis
from app.services.database import AsyncSessionLocal

_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,   "3m": 180,  "5m": 300,  "15m": 900,
    "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
    "6h": 21600, "12h": 43200, "1d": 86400,
}


def _run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── Tarea raíz (Celery Beat la llama cada minuto) ───────────────────────────

@shared_task(
    name="app.tasks.ict_scan_tasks.ict_scan_all",
    queue="default",
    max_retries=0,
)
def ict_scan_all() -> dict:
    """Escanea todos los bots con ICT habilitado."""
    try:
        return _run_async(_ict_scan_all_async())
    except Exception as exc:
        logger.error(f"[ICT] Error fatal en ict_scan_all: {exc}")
        return {"error": str(exc)}


async def _ict_scan_all_async() -> dict:
    from app.models.bot_config import BotConfig

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BotConfig)
            .options(selectinload(BotConfig.exchange_account))
            .where(
                BotConfig.status == "active",
                BotConfig.ict_scan_enabled == True,
            )
        )
        bots = result.scalars().all()

    scanned = 0
    signaled = 0
    for bot in bots:
        try:
            fired = await _scan_bot(bot)
            scanned += 1
            if fired:
                signaled += 1
        except Exception as exc:
            logger.error(f"[ICT] Error escaneando bot {bot.bot_name}: {exc}")

    logger.info(f"[ICT] Escaneo completo: {scanned} bots | {signaled} señales")
    return {"scanned": scanned, "signaled": signaled}


# ─── Lógica por bot ──────────────────────────────────────────────────────────

async def _scan_bot(bot) -> bool:
    """Retorna True si se generó y despachó una señal para este bot."""
    from app.core.ict_engine import analyze
    from app.exchanges.factory import create_exchange, create_paper_exchange

    tf = bot.timeframe
    candle_secs = _TIMEFRAME_SECONDS.get(tf, 3600)

    # Throttle — no escanear más de una vez por vela cerrada
    redis_key = f"ict:scan:{bot.id}:last"
    last_ts = sync_redis.get(redis_key)
    if last_ts:
        elapsed = datetime.now(timezone.utc).timestamp() - float(last_ts)
        if elapsed < candle_secs * 0.9:
            return False

    ict_cfg = bot.ict_config or {}
    pivot_len = int(ict_cfg.get("pivot_len", 5))
    atr_mult  = float(ict_cfg.get("atr_mult", 1.5))
    atr_len   = int(ict_cfg.get("atr_len", 14))
    entry_mode = str(ict_cfg.get("entry_mode", "ob_or_fvg"))
    candles_limit = int(ict_cfg.get("candles_limit", 200))

    # Obtener velas del exchange
    if bot.paper_balance_id is not None:
        # Paper trading — necesitamos el PaperBalance para crear el exchange
        from app.models.paper_balance import PaperBalance
        async with AsyncSessionLocal() as db:
            pb_result = await db.get(PaperBalance, bot.paper_balance_id)
        if not pb_result:
            logger.warning(f"[ICT] Bot {bot.bot_name}: PaperBalance no encontrado")
            return False
        exchange = create_paper_exchange(pb_result)
    else:
        if not bot.exchange_account:
            logger.warning(f"[ICT] Bot {bot.bot_name}: sin exchange_account")
            return False
        exchange = create_exchange(bot.exchange_account)

    try:
        candles = await exchange.get_candles(bot.symbol, tf, candles_limit)
    except Exception as exc:
        logger.warning(f"[ICT] Bot {bot.bot_name}: error obteniendo velas — {exc}")
        return False
    finally:
        await exchange.close()

    if not candles or len(candles) < 30:
        logger.warning(f"[ICT] Bot {bot.bot_name}: velas insuficientes ({len(candles) if candles else 0})")
        return False

    # Excluir la vela en curso (incompleta) para evitar señales prematuras
    closed_candles = candles[:-1]

    result = analyze(closed_candles, pivot_len, atr_mult, atr_len, entry_mode)

    # Actualizar timestamp de último escaneo (tanto si hay señal como si no)
    sync_redis.setex(redis_key, candle_secs * 2, str(datetime.now(timezone.utc).timestamp()))

    logger.debug(
        f"[ICT] {bot.bot_name} | bias={result.bias} | "
        f"break={result.last_break.kind if result.last_break else 'none'} | "
        f"signal={result.signal}"
    )

    if result.signal == "none":
        return False

    return _dispatch_signal(bot, result)


# ─── Crear y despachar señal ─────────────────────────────────────────────────

def _dispatch_signal(bot, result) -> bool:
    from app.models.signal_log import SignalLog
    from app.services.database import SessionLocal
    from app.tasks.order_tasks import execute_signal
    from app.utils.signal_hasher import generate_signal_hash

    now = datetime.now(timezone.utc)
    action = result.signal  # "long" | "short"

    # Usar el centro de la entrada zone como precio de referencia para el hash
    ref_price: float | None = None
    if result.entry_zone:
        ref_price = round((result.entry_zone[0] + result.entry_zone[1]) / 2, 8)

    sig_hash = generate_signal_hash(bot.id, action, now, ref_price)

    with SessionLocal() as db:
        # Idempotencia — misma señal dentro de la ventana de 30 s → ignorar
        exists = db.query(SignalLog).filter(SignalLog.signal_hash == sig_hash).first()
        if exists:
            logger.debug(f"[ICT] Señal duplicada para {bot.bot_name} ({action}), ignorando")
            return False

        payload = {
            "source": "ict_scan",
            "action": action,
            "price": ref_price,
            "bias": result.bias,
            "trigger": result.trigger,
            "entry_zone": list(result.entry_zone) if result.entry_zone else None,
            "break_kind": result.last_break.kind if result.last_break else None,
            "break_level": result.last_break.level if result.last_break else None,
            "ob": {
                "top": result.active_ob.top,
                "bottom": result.active_ob.bottom,
                "kind": result.active_ob.kind,
            } if result.active_ob else None,
            "fvgs_count": len(result.active_fvgs),
            "eq_highs": result.eq_highs[:5],
            "eq_lows": result.eq_lows[:5],
        }

        signal_log = SignalLog(
            bot_id=bot.id,
            signal_action=action,
            raw_payload=payload,
            signal_hash=sig_hash,
            received_at=now,
        )
        db.add(signal_log)
        db.commit()
        db.refresh(signal_log)
        signal_id = str(signal_log.id)

    logger.info(
        f"[ICT] Señal generada → {bot.bot_name} | {action.upper()} | "
        f"trigger={result.trigger} | zone={result.entry_zone}"
    )

    # Siempre orden de mercado — la zona ICT ya es el precio de entrada
    execute_signal.delay(
        bot_id=str(bot.id),
        signal_id=signal_id,
        action=action,
        price=None,
    )
    return True
