"""
Webhook de Telegram para vincular cuentas de usuario por @username.

Ruta pública (sin JWT). Telegram envía updates cuando un usuario interactúa
con el bot. Al usar /start <código>, enlazamos el chat_id con el usuario.
"""
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.database import get_db
from app.services.notifier import send_telegram_sync
from config.settings import settings

router = APIRouter(tags=["telegram"])


def _normalize_tg_username(username: str | None) -> str | None:
    if not username:
        return None
    username = username.strip().lstrip("@").lower()
    return username if username else None


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Recibe updates de Telegram y vincula chat_id con el usuario por código."""
    payload = await request.json()
    logger.debug(f"[TELEGRAM WEBHOOK] Received: {payload}")

    message = payload.get("message") or {}
    chat = message.get("chat") or {}
    from_user = message.get("from") or {}

    chat_id = chat.get("id")
    tg_username = _normalize_tg_username(from_user.get("username") or chat.get("username"))
    text = (message.get("text") or "").strip()

    if not chat_id:
        return {"ok": True, "detail": "no chat_id"}

    # Saludo simple sin código
    if text in {"/start", "/start@" + settings.telegram_bot_username} or not text.startswith("/start "):
        welcome = (
            "👋 ¡Hola! Soy el bot de notificaciones de Quantum Trading.\n\n"
            "Para vincular tu cuenta, inicia sesión en la plataforma, "
            "introduce tu usuario de Telegram en Ajustes y pulsa el enlace que te generemos."
        )
        send_telegram_sync(welcome, chat_id=str(chat_id), bot_token=settings.trading_bot_token)
        return {"ok": True, "detail": "welcome_sent"}

    # Extraer código de /start <código>
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return {"ok": True, "detail": "no_code"}

    link_code = parts[1].strip()

    # Buscar usuario por código
    result = await db.execute(select(User).where(User.telegram_link_code == link_code))
    user = result.scalar_one_or_none()

    if not user:
        send_telegram_sync(
            "❌ El enlace de vinculación no es válido o ha expirado. "
            "Genera uno nuevo desde Ajustes → Notificaciones Telegram.",
            chat_id=str(chat_id),
            bot_token=settings.trading_bot_token,
        )
        return {"ok": True, "detail": "invalid_code"}

    # Validar username si el usuario lo había indicado en la plataforma
    if user.telegram_username and tg_username and user.telegram_username != tg_username:
        send_telegram_sync(
            f"⚠️ El usuario de Telegram (@{tg_username}) no coincide con el indicado en la plataforma. "
            "Por seguridad no se ha vinculado la cuenta. "
            "Corrige el usuario en Ajustes y genera un nuevo enlace.",
            chat_id=str(chat_id),
            bot_token=settings.trading_bot_token,
        )
        return {"ok": True, "detail": "username_mismatch"}

    # Guardar chat_id y limpiar código (single-use)
    user.telegram_chat_id = str(chat_id)
    user.telegram_username = tg_username or user.telegram_username
    user.telegram_link_code = None
    await db.commit()

    send_telegram_sync(
        f"✅ <b>Cuenta vinculada</b>\n\n"
        f"Hola {user.username}, ya recibirás tus alertas de trading aquí.\n\n"
        f"Puedes desactivarlas cuando quieras desde Ajustes → Notificaciones Telegram.",
        chat_id=str(chat_id),
        bot_token=settings.trading_bot_token,
    )

    logger.info(f"[TELEGRAM] Usuario {user.username} vinculado con chat_id {chat_id}")
    return {"ok": True, "detail": "linked"}
