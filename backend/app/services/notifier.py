"""
Servicio de notificaciones: Telegram y Discord.

- send_*_sync(): para Celery tasks (síncronas)
- Las versiones async se usan directamente con httpx si se necesitan desde FastAPI
"""
import httpx
from loguru import logger

from config.settings import settings


def _telegram_url() -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"


def send_telegram_sync(message: str, chat_id: str | None = None) -> None:
    """Envía un mensaje a Telegram. Si chat_id es None, usa el global."""
    if not settings.telegram_bot_token:
        return
    target_chat_id = chat_id or settings.telegram_chat_id
    if not target_chat_id:
        return
    try:
        resp = httpx.post(
            _telegram_url(),
            json={
                "chat_id":    target_chat_id,
                "text":       message,
                "parse_mode": "HTML",
            },
            timeout=5,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"Telegram error: {exc}")


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
    chat_id: str | None = None, is_limit: bool = False
) -> None:
    emoji = "🟢" if side == "long" else "🔴"
    if is_limit:
        msg = (
            f"{emoji} <b>ORDEN LÍMITE COLOCADA</b>\n"
            f"Bot: {bot_name}\n"
            f"Par: {symbol} | {side.upper()}\n"
            f"Precio límite: {entry:.4f} USDT\n"
            f"SL: {sl:.4f} USDT\n"
            f"<i>La posición se abrirá cuando el precio alcance el límite.</i>"
        )
    else:
        msg = (
            f"{emoji} <b>TRADE ABIERTO</b>\n"
            f"Bot: {bot_name}\n"
            f"Par: {symbol} | {side.upper()}\n"
            f"Entrada: {entry:.4f} USDT\n"
            f"SL: {sl:.4f} USDT"
        )
    send_telegram_sync(msg, chat_id=chat_id)
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**").replace("<i>", "*").replace("</i>", "*"))


def notify_trade_partial(
    bot_name: str, symbol: str, side: str, tp_level: int,
    close_percent: float, fill_price: float, partial_pnl: float,
    chat_id: str | None = None
) -> None:
    emoji = "🎯" if partial_pnl >= 0 else "⚠️"
    msg = (
        f"{emoji} <b>TAKE PROFIT PARCIAL</b>\n"
        f"Bot: {bot_name}\n"
        f"Par: {symbol} | {side.upper()}\n"
        f"TP{tp_level} alcanzado\n"
        f"Cierre: {close_percent:.1f}% @ {fill_price:.4f} USDT\n"
        f"PnL parcial: {partial_pnl:+.2f} USDT"
    )
    send_telegram_sync(msg, chat_id=chat_id)
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_trade_closed(
    bot_name: str, symbol: str, side: str, pnl: float,
    chat_id: str | None = None
) -> None:
    emoji = "✅" if pnl >= 0 else "❌"
    msg = (
        f"{emoji} <b>TRADE CERRADO</b>\n"
        f"Bot: {bot_name}\n"
        f"Par: {symbol} | {side.upper()}\n"
        f"PnL: {pnl:+.2f} USDT"
    )
    send_telegram_sync(msg, chat_id=chat_id)
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
    send_telegram_sync(msg, chat_id=chat_id)
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_error(bot_name: str, error: str, chat_id: str | None = None) -> None:
    msg = f"⚠️ <b>ERROR — {bot_name}</b>\n{error[:300]}"
    send_telegram_sync(msg, chat_id=chat_id)
    if not chat_id:
        send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_circuit_breaker(bot_name: str, symbol: str, consecutive_losses: int) -> None:
    msg = (
        f"🚨 <b>CIRCUIT BREAKER ACTIVADO</b>\n\n"
        f"Bot: <b>{bot_name}</b>\n"
        f"Par: {symbol}\n"
        f"Motivo: {consecutive_losses} pérdidas consecutivas\n\n"
        f"⚠️ El bot ha sido pausado automáticamente.\n"
        f"Revisa las condiciones del mercado antes de reactivarlo."
    )
    send_telegram_sync(msg)
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
        f"🚨 <b>SEÑAL IA — STRONG+CLEAR</b>\n\n"
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

    send_telegram_sync(msg)
    plain = (msg
             .replace("<b>", "**").replace("</b>", "**")
             .replace("<i>", "*").replace("</i>", "*")
             .replace("<code>", "`").replace("</code>", "`"))
    send_discord_sync(plain)


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
    send_telegram_sync(msg)
    send_discord_sync(msg)
