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


def send_telegram_sync(message: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    try:
        resp = httpx.post(
            _telegram_url(),
            json={
                "chat_id":    settings.telegram_chat_id,
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


def notify_trade_opened(bot_name: str, symbol: str, side: str, entry: float, sl: float) -> None:
    emoji = "🟢" if side == "long" else "🔴"
    msg = (
        f"{emoji} <b>TRADE ABIERTO</b>\n"
        f"Bot: {bot_name}\n"
        f"Par: {symbol} | {side.upper()}\n"
        f"Entrada: {entry:.4f} USDT\n"
        f"SL: {sl:.4f} USDT"
    )
    send_telegram_sync(msg)
    send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_trade_closed(
    bot_name: str, symbol: str, side: str, pnl: float
) -> None:
    emoji = "✅" if pnl >= 0 else "❌"
    msg = (
        f"{emoji} <b>TRADE CERRADO</b>\n"
        f"Bot: {bot_name}\n"
        f"Par: {symbol} | {side.upper()}\n"
        f"PnL: {pnl:+.2f} USDT"
    )
    send_telegram_sync(msg)
    send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))


def notify_error(bot_name: str, error: str) -> None:
    msg = f"⚠️ <b>ERROR — {bot_name}</b>\n{error[:300]}"
    send_telegram_sync(msg)
    send_discord_sync(msg.replace("<b>", "**").replace("</b>", "**"))
