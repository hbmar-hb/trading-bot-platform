"""
Tarea Celery que ejecuta el motor ICT sobre los bots con alert trigger configurado.

Ciclo (disparado por Beat cada 60 s):
  1. Obtener bots activos con trigger_indicator IS NOT NULL (o ict_scan_enabled legacy)
  2. Agrupar por (symbol, timeframe) para reutilizar las mismas velas
  3. Para cada bot, aplicar throttle según timing:
       - candle_close:  esperar cierre completo de vela (1 escaneo por vela)
       - intracandle:   escanear cada trigger_interval_minutes (incluye vela en curso)
  4. Correr análisis ICT — filtrar por grade >= trigger_min_grade
  5. Verificar min_confirm_candles (señal debe persistir N escaneos)
  6. Si todo ok → crear SignalLog + despachar execute_signal
"""
import asyncio
import gc
from datetime import datetime, timezone

from celery import shared_task
from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.services.cache import sync_redis
from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal

_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,   "3m": 180,  "5m": 300,  "15m": 900,
    "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
    "6h": 21600, "12h": 43200, "1d": 86400,
}

def _grade_allowed(signal_grade: str, allowed_grades_str: str) -> bool:
    """
    Comprueba si el grade de la señal está en la lista configurada.

    allowed_grades_str puede ser:
      - "A+"          solo BOS alcistas (long)
      - "A"           solo CHoCH (reversiones, ambas direcciones)
      - "A-"          solo BOS bajistas (short)
      - "A+,A"        longs: BOS + reversión alcista
      - "A,A-"        shorts: reversión bajista + BOS
      - "A+,A,A-"     todo (default)
    """
    if not allowed_grades_str or allowed_grades_str.strip() in ("", "all"):
        return True
    allowed = {g.strip() for g in allowed_grades_str.split(",")}
    return signal_grade in allowed


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ─── Tarea raíz (Celery Beat la llama cada minuto) ───────────────────────────

@shared_task(
    name="app.tasks.ict_scan_tasks.ict_scan_all",
    queue="default",
    max_retries=0,
)
def ict_scan_all() -> dict:
    """Escanea todos los bots con ICT trigger configurado."""
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
                BotConfig.indicator_enabled == True,
                BotConfig.alerts_only == False,
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
        finally:
            # Forzar liberación de memoria entre bots para evitar acumulación
            gc.collect()

    logger.info(f"[ICT] Escaneo completo: {scanned} bots | {signaled} señales")
    return {"scanned": scanned, "signaled": signaled}


# ─── Lógica por bot ──────────────────────────────────────────────────────────

async def _scan_bot(bot) -> bool:
    """Retorna True si se generó y despachó una señal para este bot."""
    from app.core.ict_engine import analyze
    from app.exchanges.factory import create_exchange, create_paper_exchange

    # ── Configuración de trigger ──────────────────────────────────────────
    # Soporte legacy: bots con ict_scan_enabled sin trigger_indicator
    indicator = bot.trigger_indicator or "ict"
    scan_tf   = bot.trigger_timeframe or bot.timeframe
    min_grade = getattr(bot, 'trigger_min_grade', 'A') or 'A'
    timing    = getattr(bot, 'trigger_timing', 'candle_close') or 'candle_close'
    interval_m = int(getattr(bot, 'trigger_interval_minutes', 5) or 5)
    min_confirm = int(getattr(bot, 'min_confirm_candles', 1) or 1)

    if indicator not in ("ict", "quantum_gold"):
        logger.debug(f"[ICT] Bot {bot.bot_name}: indicador '{indicator}' no soportado aún")
        return False

    candle_secs = _TIMEFRAME_SECONDS.get(scan_tf, 3600)

    # ── Throttle dinámico según timing ───────────────────────────────────
    # En modo intracandle, interval_m = número de sub-escaneos por vela
    # El intervalo real = candle_secs / interval_m, con mínimo 60s (cadencia del Beat)
    if timing == "intracandle":
        sub_interval_secs = max(60, candle_secs / max(1, interval_m))
    else:
        sub_interval_secs = candle_secs

    redis_key = f"ict:scan:{bot.id}:last"
    last_ts = sync_redis.get(redis_key)
    if last_ts:
        elapsed = datetime.now(timezone.utc).timestamp() - float(last_ts)
        if elapsed < sub_interval_secs * 0.9:
            return False

    # ── Obtener velas ─────────────────────────────────────────────────────
    ict_cfg = bot.ict_config or {}
    pivot_len     = int(ict_cfg.get("pivot_len", 5))
    atr_mult      = float(ict_cfg.get("atr_mult", 0.3))
    atr_len       = int(ict_cfg.get("atr_len", 14))
    entry_mode    = str(ict_cfg.get("entry_mode", "ob_or_fvg"))
    candles_limit = int(ict_cfg.get("candles_limit", 200))

    if bot.paper_balance_id is not None:
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
        candles = await exchange.get_candles(bot.symbol, scan_tf, candles_limit)
    except Exception as exc:
        logger.warning(f"[ICT] Bot {bot.bot_name}: error obteniendo velas — {exc}")
        return False
    finally:
        await exchange.close()

    if not candles or len(candles) < 30:
        logger.warning(f"[ICT] Bot {bot.bot_name}: velas insuficientes ({len(candles) if candles else 0})")
        return False

    # ── Selección de velas según timing ──────────────────────────────────
    if timing == "intracandle":
        analysis_candles = candles           # incluye vela en curso
    else:
        analysis_candles = candles[:-1]      # solo velas cerradas

    if indicator == "quantum_gold":
        from app.engines.quantum_gold_engine import analyze as qg_analyze
        qg_cfg = bot.ict_config or {}   # reutilizamos ict_config para params QG
        result = qg_analyze(
            analysis_candles,
            ema_fast           = int(qg_cfg.get("ema_fast",           9)),
            ema_mid            = int(qg_cfg.get("ema_mid",            21)),
            ema_slow           = int(qg_cfg.get("ema_slow",           50)),
            ema_trend          = int(qg_cfg.get("ema_trend",         200)),
            st_atr_len         = int(qg_cfg.get("st_atr_len",         10)),
            st_factor          = float(qg_cfg.get("st_factor",        3.0)),
            bb_len             = int(qg_cfg.get("bb_len",             20)),
            bb_std             = float(qg_cfg.get("bb_std",           2.0)),
            bb_sqz_threshold   = float(qg_cfg.get("bb_sqz_threshold", 0.9)),
            rsi_len            = int(qg_cfg.get("rsi_len",            14)),
            rsi_bull_lo        = int(qg_cfg.get("rsi_bull_lo",        52)),
            rsi_bull_hi        = int(qg_cfg.get("rsi_bull_hi",        68)),
            rsi_bear_lo        = int(qg_cfg.get("rsi_bear_lo",        32)),
            rsi_bear_hi        = int(qg_cfg.get("rsi_bear_hi",        48)),
            vol_len            = int(qg_cfg.get("vol_len",            20)),
            vol_mult           = float(qg_cfg.get("vol_mult",         1.4)),
            atr_len            = int(qg_cfg.get("atr_len",            14)),
            tp_mult            = float(qg_cfg.get("tp_mult",          2.0)),
            sl_mult            = float(qg_cfg.get("sl_mult",          1.0)),
            use_trend_filter   = bool(qg_cfg.get("use_trend_filter",  True)),
            min_atr_filter     = float(qg_cfg.get("min_atr_filter",   3.0)),
            use_sess           = bool(qg_cfg.get("use_sess",          True)),
        )
    else:
        result = analyze(analysis_candles, pivot_len, atr_mult, atr_len, entry_mode)

    # Actualizar timestamp de último escaneo
    ttl = int(sub_interval_secs * 3)
    sync_redis.setex(redis_key, ttl, str(datetime.now(timezone.utc).timestamp()))

    logger.debug(
        f"[{indicator.upper()}] {bot.bot_name} | tf={scan_tf} | timing={timing} | "
        f"bias={result.bias} | signal={result.signal} | grade={result.grade}"
    )

    if result.signal == "none":
        return False

    # ── Filtro por grade ──────────────────────────────────────────────────
    if not _grade_allowed(result.grade, min_grade):
        logger.debug(
            f"[ICT] {bot.bot_name}: señal {result.signal} descartada — "
            f"grade={result.grade} no está en permitidos={min_grade}"
        )
        return False

    # ── Confirmación de velas (min_confirm_candles) ───────────────────────
    if min_confirm > 1:
        confirm_key = f"ict:confirm:{bot.id}:{result.signal}:{result.grade}"
        raw = sync_redis.get(confirm_key)
        count = int(raw) + 1 if raw else 1
        if count < min_confirm:
            sync_redis.setex(confirm_key, candle_secs * (min_confirm + 1), str(count))
            logger.debug(
                f"[ICT] {bot.bot_name}: confirmación {count}/{min_confirm} para {result.signal} {result.grade}"
            )
            return False
        # Confirmación completa — limpiar contador
        sync_redis.delete(confirm_key)
    else:
        # Reset confirmación si la señal cambia
        sync_redis.delete(f"ict:confirm:{bot.id}:long:{result.grade}")
        sync_redis.delete(f"ict:confirm:{bot.id}:short:{result.grade}")

    return _dispatch_signal(bot, result)


# ─── Crear y despachar señal ─────────────────────────────────────────────────

def _dispatch_signal(bot, result) -> bool:
    from app.models.signal_log import SignalLog
    from app.services.database import SessionLocal
    from app.tasks.order_tasks import execute_signal
    from app.utils.signal_hasher import generate_signal_hash

    now = datetime.now(timezone.utc)
    action = result.signal  # "long" | "short"

    ref_price: float | None = None
    if result.entry_zone:
        ref_price = round((result.entry_zone[0] + result.entry_zone[1]) / 2, 8)

    sig_hash = generate_signal_hash(bot.id, action, now, ref_price)

    with SessionLocal() as db:
        exists = db.query(SignalLog).filter(SignalLog.signal_hash == sig_hash).first()
        if exists:
            logger.debug(f"[ICT] Señal duplicada para {bot.bot_name} ({action}), ignorando")
            return False

        payload = {
            "source":      "indicator",
            "action":      action,
            "grade":       result.grade,
            "price":       ref_price,
            "bias":        result.bias,
            "trigger":     result.trigger,
            "entry_zone":  list(result.entry_zone) if result.entry_zone else None,
            "break_kind":  result.last_break.kind if result.last_break else None,
            "break_level": result.last_break.level if result.last_break else None,
            "ob": {
                "top":    result.active_ob.top,
                "bottom": result.active_ob.bottom,
                "kind":   result.active_ob.kind,
            } if result.active_ob else None,
            "fvgs_count": len(result.active_fvgs),
            "eq_highs":   result.eq_highs[:5],
            "eq_lows":    result.eq_lows[:5],
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
        f"[ICT] Alerta disparada → {bot.bot_name} | {action.upper()} {result.grade} | "
        f"trigger={result.trigger} | zone={result.entry_zone}"
    )

    execute_signal.delay(
        bot_id=str(bot.id),
        signal_id=signal_id,
        action=action,
        price=None,
    )
    return True
