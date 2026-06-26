"""
Servicio de notificaciones: Telegram y Discord.

- send_*_sync(): para Celery tasks (síncronas)
- Las versiones async se usan directamente con httpx si se necesitan desde FastAPI
"""
import html
import time
import httpx
from loguru import logger

from config.settings import settings

_TELEGRAM_MAX_RETRIES = 3
_TELEGRAM_RETRY_DELAY = 2  # seconds between retries


def _telegram_url(bot_token: str | None = None) -> str:
    token = bot_token or settings.trading_bot_token
    return f"https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_sync(
    message: str,
    chat_id: str | None = None,
    thread_id: int | None = None,
    level: str = "essential",
    bot_token: str | None = None,
) -> None:
    """Envía un mensaje a Telegram con reintentos automáticos.

    level: "essential" (trades, circuit breaker, kill switch) or "verbose" (errors, rejections, alerts).
    When TELEGRAM_NOTIFY_LEVEL=essential, verbose messages are skipped.

    bot_token: token específico del bot de Telegram. Si es None se usa el bot de
    trading/IA (settings.trading_bot_token).
    """
    if settings.telegram_notify_level == "essential" and level == "verbose":
        return  # skip noise
    token = bot_token or settings.trading_bot_token
    if not token:
        return
    target_chat_id = chat_id or settings.telegram_chat_id
    if not target_chat_id:
        return
    payload = {
        "chat_id": target_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id

    url = _telegram_url(token)
    last_exc: Exception | None = None

    for attempt in range(1, _TELEGRAM_MAX_RETRIES + 1):
        try:
            resp = httpx.post(url, json=payload, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                err_code = data.get("error_code")
                description = data.get("description", "")
                # Rate-limit: wait and retry
                if err_code == 429:
                    retry_after = data.get("parameters", {}).get("retry_after", _TELEGRAM_RETRY_DELAY)
                    logger.warning(
                        f"[Telegram] Rate limit (intento {attempt}/{_TELEGRAM_MAX_RETRIES}), "
                        f"reintentando en {retry_after}s"
                    )
                    time.sleep(retry_after)
                    continue
                logger.error(
                    f"[Telegram] Mensaje rechazado (chat={target_chat_id} thread={thread_id} "
                    f"intento={attempt}): {err_code} — {description}"
                )
                return
            msg_id = data["result"]["message_id"]
            logger.info(
                f"[Telegram] ✓ msg_id={msg_id} chat={target_chat_id} thread={thread_id}"
            )
            return
        except Exception as exc:
            last_exc = exc
            if attempt < _TELEGRAM_MAX_RETRIES:
                logger.warning(
                    f"[Telegram] Error en intento {attempt}/{_TELEGRAM_MAX_RETRIES} "
                    f"(chat={target_chat_id} thread={thread_id}): {exc} — reintentando en {_TELEGRAM_RETRY_DELAY}s"
                )
                time.sleep(_TELEGRAM_RETRY_DELAY)
            else:
                logger.error(
                    f"[Telegram] Fallo definitivo tras {_TELEGRAM_MAX_RETRIES} intentos "
                    f"(chat={target_chat_id} thread={thread_id}): {last_exc}"
                )


def send_discord_sync(message: str) -> None:
    if not settings.discord_webhook_url:
        return
    try:
        resp = httpx.post(
            settings.discord_webhook_url,
            json={"content": message},
            timeout=5,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"Discord error: {exc}")


def notify_trade_opened(
    bot_name: str, symbol: str, side: str, entry: float, sl: float,
    chat_id: str | None = None, is_limit: bool = False, source: str = "bot",
    tp1: float | None = None, tp2: float | None = None, tp3: float | None = None,
    trailing_config: dict | None = None,
    breakeven_config: dict | None = None,
    dynamic_sl_config: dict | None = None,
    leverage: int | None = None,
    risk_pct: float | None = None,
    quantity: float | None = None,
    order_id: str | None = None,
    signal_id: str | None = None,
    explanation: str | None = None,
    autopilot_status: str = "Aprobado",
    timeframe: str | None = None,
) -> None:
    emoji = "🟢" if side == "long" else "🔴"
    side_label = "LONG (BUY)" if side == "long" else "SHORT (SELL)"
    origin = " IA" if source == "ai_bot" else ""

    # Build TP lines
    tp_lines = ""
    if tp1:
        tp_lines += f"\n🎯 Take Profit: {tp1:.4f}"
    if tp2:
        tp_lines += f"\n🎯 Take Profit 2: {tp2:.4f}"
    if tp3:
        tp_lines += f"\n🎯 Take Profit 3: {tp3:.4f}"

    # Build risk management lines
    risk_lines = ""
    if breakeven_config and breakeven_config.get("enabled"):
        risk_lines += f"\n🛡️ BE @ {breakeven_config.get('activation_r', 1.0)}R (lock {breakeven_config.get('lock_profit', 0)}%)"
    if trailing_config and trailing_config.get("enabled"):
        risk_lines += f"\n📉 Trailing @ {trailing_config.get('activation_r', 1.5)}R (callback {trailing_config.get('callback_rate', 1.0)}%)"
    if dynamic_sl_config and dynamic_sl_config.get("enabled"):
        risk_lines += f"\n⚙️ Dynamic SL step {dynamic_sl_config.get('step_r', 0.5)}R (max {dynamic_sl_config.get('max_steps', 6)} steps)"

    # Leverage, risk & timeframe
    lev_line = f"\n⚙️ Apalancamiento: {leverage}x" if leverage else ""
    risk_line = f"\n📊 Riesgo: {risk_pct:.2f}% del balance" if risk_pct else ""
    tf_line = f"\n⏱ Timeframe: {timeframe}" if timeframe else ""

    # Explanation
    explanation_line = ""
    if explanation:
        safe_explanation = html.escape(explanation)
        explanation_line = f"\n\n📝 <b>Nota</b>\n{safe_explanation}"

    # Signal ID
    signal_id_line = f"\n🆔 {signal_id}" if signal_id else ""

    # Autopilot
    autopilot_line = f"\n🤖 Autopilot: {autopilot_status}"

    # Order summary
    order_line = ""
    if order_id:
        qty_str = f" qty={quantity:.4f}" if quantity else ""
        lev_str = f" lev={leverage}x" if leverage else ""
        risk_str = f" risk={risk_pct:.2f}%" if risk_pct else ""
        order_line = (
            f"\n\n<i>Orden enviada ({symbol} {side.upper()}){qty_str}{lev_str}{risk_str} "
            f"(orderId: {order_id})</i>"
        )

    if is_limit:
        msg = (
            f"📣 <b>Nueva señal</b>\n"
            f"📌 {symbol} • {emoji} {side_label}{origin}\n"
            f"{tf_line}"
            f"\n💰 Entry: {entry:.4f}"
            f"\n🛑 Stop Loss: {sl:.4f}"
            f"{tp_lines}"
            f"{lev_line}"
            f"{risk_line}"
            f"\n👤 Trader: IA"
            f"{explanation_line}"
            f"{signal_id_line}"
            f"{autopilot_line}"
            f"{order_line}"
            f"{risk_lines}\n"
            f"\n<i>La posición se abrirá cuando el precio alcance el límite.</i>"
        )
    else:
        msg = (
            f"📣 <b>Nueva señal</b>\n"
            f"📌 {symbol} • {emoji} {side_label}{origin}\n"
            f"{tf_line}"
            f"\n💰 Entry: {entry:.4f}"
            f"\n🛑 Stop Loss: {sl:.4f}"
            f"{tp_lines}"
            f"{lev_line}"
            f"{risk_line}"
            f"\n👤 Trader: IA"
            f"{explanation_line}"
            f"{signal_id_line}"
            f"{autopilot_line}"
            f"{order_line}"
            f"{risk_lines}"
        )
    send_telegram_sync(msg, chat_id=chat_id, level="essential")
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**").replace("<i>", "*").replace("</i>", "*"))


def notify_trade_partial(
    bot_name: str, symbol: str, side: str, tp_level: int,
    close_percent: float, fill_price: float, partial_pnl: float,
    chat_id: str | None = None, source: str = "bot"
) -> None:
    emoji = "🎯" if partial_pnl >= 0 else "⚠️"
    origin = " IA" if source == "ai_bot" else ""
    msg = (
        f"{emoji} <b>TAKE PROFIT PARCIAL{origin}</b>\n"
        f"Bot: {bot_name}\n"
        f"Par: {symbol} | {side.upper()}\n"
        f"TP{tp_level} alcanzado\n"
        f"Cierre: {close_percent:.1f}% @ {fill_price:.4f} USDT\n"
        f"PnL parcial: {partial_pnl:+.2f} USDT"
    )
    send_telegram_sync(msg, chat_id=chat_id, level="essential")
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_trade_closed(
    bot_name: str, symbol: str, side: str, pnl: float,
    chat_id: str | None = None, source: str = "bot",
    entry_price: float | None = None,
    exit_price: float | None = None,
    quantity: float | None = None,
    leverage: int | None = None,
    timeframe: str | None = None,
) -> None:
    emoji = "✅" if pnl >= 0 else "❌"
    origin = " IA" if source == "ai_bot" else ""

    # ROI with leverage = PnL / margin * 100, where margin = notional / leverage
    roi_line = ""
    if entry_price and quantity and leverage:
        try:
            margin = (entry_price * quantity) / leverage
            if margin > 0:
                roi_leveraged = (pnl / margin) * 100
                roi_line = f"\n📈 ROI (apalancado): {roi_leveraged:+.2f}%"
        except Exception:
            pass

    entry_line = f"\n💰 Entry: {entry_price:.4f}" if entry_price else ""
    exit_line = f"\n🏁 Exit: {exit_price:.4f}" if exit_price else ""
    lev_line = f"\n⚙️ Apalancamiento: {leverage}x" if leverage else ""
    tf_line = f"\n⏱ Timeframe: {timeframe}" if timeframe else ""

    msg = (
        f"{emoji} <b>TRADE CERRADO{origin}</b>\n"
        f"Bot: {bot_name}\n"
        f"Par: {symbol} | {side.upper()}"
        f"{tf_line}"
        f"{entry_line}"
        f"{exit_line}"
        f"{lev_line}"
        f"{roi_line}\n"
        f"💵 PnL: {pnl:+.2f} USDT"
    )
    send_telegram_sync(msg, chat_id=chat_id, level="essential")
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_sl_moved(
    bot_name: str, symbol: str, side: str, old_sl: float, new_sl: float,
    chat_id: str | None = None
) -> None:
    msg = (
        f"🛡️ <b>STOP LOSS MOVIDO</b>\n"
        f"Bot: {bot_name}\n"
        f"Par: {symbol} | {side.upper()}\n"
        f"SL: {old_sl:.4f} → {new_sl:.4f} USDT"
    )
    send_telegram_sync(msg, chat_id=chat_id, level="essential")
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_error(bot_name: str, error: str, chat_id: str | None = None) -> None:
    msg = f"⚠️ <b>ERROR — {bot_name}</b>\n{error[:300]}"
    send_telegram_sync(msg, chat_id=chat_id, level="verbose")
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_circuit_breaker(
    bot_name: str,
    symbol: str,
    reason: str,
    title: str = "CIRCUIT BREAKER ACTIVADO",
    footer: str | None = None,
) -> None:
    msg = f"🚨 <b>{title}</b>\n\nBot: <b>{bot_name}</b>\nPar: {symbol}\nMotivo: {reason}\n\n"
    if footer:
        msg += footer
    else:
        msg += (
            "⚠️ El tier de calidad está bloqueado. El bot sigue activo, pero ignorará señales "
            "de este tier hasta que el win rate se recupere (≥50%) o pasen 24h.\n"
            "Revisa las condiciones del mercado antes de reactivar manualmente."
        )
    send_telegram_sync(msg, level="essential")
    send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_ai_signal(
    ticker: str, timeframe: str, direction: str,
    score: float, quality_score: float, confidence: str,
    entry: float, sl: float, tp1: float, tp2: float,
    components: dict, warnings: list,
    htf_bias: str | None = None,
) -> None:
    """Alert for every STRONG+CLEAR AI signal, regardless of whether a bot is active."""
    emoji   = "🟢" if direction == "long" else "🔴"
    dir_lbl = "LONG" if direction == "long" else "SHORT"

    # R:R computed from prices
    risk = abs(entry - sl)
    reward = abs(tp1 - entry)
    rr = round(reward / risk, 1) if risk > 0 else 0.0

    htf_line   = f"\n🔭 HTF: {htf_bias.upper()}" if htf_bias else ""
    comp_lines = "\n".join(f"  ✅ {v}" for v in list(components.values())[:5])
    warn_lines = "\n".join(f"  ⚠️ {w}" for w in warnings[:2])

    msg = (
        f"🚨 <b>SEÑAL IA</b>\n\n"
        f"{emoji} <b>{ticker}</b> | {dir_lbl} | {timeframe}{htf_line}\n"
        f"💯 Confluencia: {score:.0f}/100 ({confidence})\n"
        f"⭐ Calidad: {quality_score:.0f}/100\n\n"
        f"📍 Entrada:  <code>{entry:,.4f}</code>\n"
        f"🛡️ SL:       <code>{sl:,.4f}</code>\n"
        f"🎯 TP1:      <code>{tp1:,.4f}</code>\n"
        f"🏆 TP2:      <code>{tp2:,.4f}</code>\n"
        f"📐 R:R: {rr:.1f}×\n"
    )
    if comp_lines:
        msg += f"\n<b>Confluencias:</b>\n{comp_lines}\n"
    if warn_lines:
        msg += f"\n<b>Avisos:</b>\n{warn_lines}\n"

    send_telegram_sync(msg, level="verbose")
    plain = (msg
             .replace("<b>", "**").replace("</b>", "**")
             .replace("<i>", "*").replace("</i>", "*")
             .replace("<code>", "`").replace("</code>", "`"))
    send_discord_sync(plain)


def notify_trade_rejected(
    bot_name: str, symbol: str, side: str, reason: str,
    chat_id: str | None = None
) -> None:
    emoji = "🚫"
    msg = (
        f"{emoji} <b>TRADE RECHAZADO — CONFLICTO</b>\n"
        f"Bot: {bot_name}\n"
        f"Par: {symbol} | {side.upper()}\n"
        f"Motivo: {reason}"
    )
    send_telegram_sync(msg, chat_id=chat_id, level="verbose")
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_position_override(
    closed_bot_name: str, opened_bot_name: str,
    symbol: str, side: str, chat_id: str | None = None
) -> None:
    msg = (
        f"🔄 <b>POSICIÓN CERRADA POR PRIORIDAD IA</b>\n"
        f"Bot cerrado: {closed_bot_name}\n"
        f"Bot abierto: {opened_bot_name}\n"
        f"Par: {symbol} | {side.upper()}\n"
        f"<i>El Bot IA tiene prioridad y ha reemplazado la posición.</i>"
    )
    send_telegram_sync(msg, chat_id=chat_id, level="verbose")
    if not chat_id:
        send_discord_sync(
            msg.replace("<b>", "**").replace("</b>", "**")
            .replace("<i>", "*").replace("</i>", "*")
        )


def notify_kill_switch(
    user_name: str, closed: int, paused: int, pnl: float, elapsed: float,
    chat_id: str | None = None
) -> None:
    emoji = "🚨"
    pnl_emoji = "✅" if pnl >= 0 else "❌"
    msg = (
        f"{emoji} <b>KILL SWITCH ACTIVADO</b>\n\n"
        f"Usuario: {user_name}\n"
        f"Posiciones cerradas: {closed}\n"
        f"Bots pausados: {paused}\n"
        f"PnL total: {pnl_emoji} {pnl:+.2f} USDT\n"
        f"Tiempo: {elapsed:.2f}s"
    )
    send_telegram_sync(msg, chat_id=chat_id, level="essential")
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_watchlist_coverage_alert(bots: list[dict]) -> None:
    """Alert when active AI bots are not covered by the AI watchlist."""
    if not bots:
        return
    bot_lines = "\n".join(
        f"  • {b['bot_name']} ({b['symbol']} {b['timeframe']})"
        for b in bots
    )
    msg = (
        f"⚠️ <b>AI WATCHLIST COVERAGE ALERT</b>\n\n"
        f"{len(bots)} bot(s) activo(s) sin cobertura de watchlist:\n"
        f"{bot_lines}\n\n"
        f"<i>Estos bots no recibirán señales AI hasta que su par/timeframe "
        f"se añada a la watchlist.</i>"
    )
    send_telegram_sync(msg, level="verbose")
    send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**").replace("<i>", "*").replace("</i>", "*"))


def notify_auto_optimized(
    bot_name: str, symbol: str, changes: dict, health_score: int, crisis_mode: bool = False
) -> None:
    emoji = "!" if crisis_mode else "*"
    crisis_str = " (MODO CRISIS)" if crisis_mode else ""
    changes_lines = "\n".join(
        f"  - {k.replace('_', ' ').title()}: {v}"
        for k, v in changes.items()
    )
    msg = (
        f"{emoji} AUTO-OPTIMIZACION APLICADA{crisis_str}\n"
        f"Bot: {bot_name}\n"
        f"Par: {symbol}\n"
        f"Salud: {health_score}/100\n"
        f"Cambios:\n{changes_lines}"
    )
    send_telegram_sync(msg, level="essential")
    send_discord_sync(msg)


def notify_webhook_signal(
    symbol: str,
    action: str,
    price: float | None,
    strategy: str | None = None,
    chat_id: str | None = None,
    thread_id: int | None = None,
    alerts_only: bool = False,
    timeframe: str | None = None,
    bot_name: str | None = None,
) -> None:
    """Notifica una señal recibida desde TradingView webhook.

    Formato:
        📣 Nueva señal
        📌 BTC/USDT:USDT • 🔴 SHORT (SELL) QUANTUM
        ⏱ Temporalidad: 15m
        💰 Entry: 62778.3000

    Las señales de webhook se envían siempre con QUANTUM BOT NOTIFIER.
    Destino prioritario: TELEGRAM_QUANTUM_GROUP_CHAT_ID / TELEGRAM_QUANTUM_THREAD_ID.
    Si no están configurados, se usa la configuración por bot (chat_id/thread_id).
    """
    emoji = "🟢" if action == "long" else "🔴"
    side_label = "LONG (BUY)" if action == "long" else "SHORT (SELL)"
    strategy_label = f" {strategy}" if strategy else ""

    tf_line = f"\n⏱ Temporalidad: {timeframe}" if timeframe else ""
    price_line = f"\n💰 Entry: {price:.4f}" if price else ""
    bot_line = f"\n🤖 Bot: {bot_name}" if bot_name else ""

    msg = (
        f"📣 <b>Nueva señal</b>\n"
        f"📌 {symbol} • {emoji} {side_label}{strategy_label}"
        f"{tf_line}"
        f"{price_line}"
        f"{bot_line}"
    )
    # Las señales van siempre por QUANTUM BOT NOTIFIER.
    bot_token = settings.quantum_bot_token
    target_chat_id = settings.telegram_quantum_group_chat_id or chat_id
    target_thread_id = settings.telegram_quantum_thread_id or thread_id
    if not target_chat_id:
        return  # no hay destino configurado
    send_telegram_sync(
        msg,
        chat_id=target_chat_id,
        thread_id=target_thread_id,
        level="essential",
        bot_token=bot_token,
    )
