import asyncio
import json
import re
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt
from loguru import logger

from app.api.websocket.manager import ws_manager
from app.models.user import User
from config.settings import settings

_MENTION_RE = re.compile(r"@([a-zA-Z0-9_]+)")

router = APIRouter(tags=["websocket"])


async def _get_user_active_symbols(user_id: uuid.UUID) -> list[str]:
    """Devuelve símbolos únicos de bots activos/pausados y posiciones abiertas/pendientes."""
    from app.models.bot_config import BotConfig
    from app.models.exchange_account import ExchangeAccount
    from app.models.position import Position
    from app.services.database import AsyncSessionLocal
    from sqlalchemy import select

    symbols: set[str] = set()

    async with AsyncSessionLocal() as db:
        # Bots activos/pausados (reales)
        result = await db.execute(
            select(BotConfig.symbol)
            .join(ExchangeAccount, BotConfig.exchange_account_id == ExchangeAccount.id)
            .where(
                ExchangeAccount.user_id == user_id,
                BotConfig.status.in_(["active", "paused"]),
            )
            .distinct()
        )
        for row in result.all():
            symbols.add(row[0])

        # Bots de paper trading
        paper_result = await db.execute(
            select(BotConfig.symbol)
            .where(
                BotConfig.user_id == user_id,
                BotConfig.paper_balance_id.is_not(None),
                BotConfig.status.in_(["active", "paused"]),
            )
            .distinct()
        )
        for row in paper_result.all():
            symbols.add(row[0])

        # Posiciones abiertas o pendientes (via BotConfig para obtener user_id)
        pos_result = await db.execute(
            select(Position.symbol)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(
                BotConfig.user_id == user_id,
                Position.status.in_(["open", "pending_limit"]),
            )
            .distinct()
        )
        for row in pos_result.all():
            symbols.add(row[0])

    return list(symbols)


async def _get_user_from_token(token: str) -> User | None:
    """Decodifica el JWT, valida tipo y estado del usuario en BD."""
    from app.models.user import User
    from app.services.database import AsyncSessionLocal
    from sqlalchemy import select

    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], audience=settings.jwt_audience)
        sub = payload.get("sub")
        if not sub or payload.get("type") != "access":
            return None
        if payload.get("iss") != settings.jwt_issuer:
            return None
        user_uuid = uuid.UUID(sub)
    except (JWTError, ValueError):
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            return None
    return user


# Rate limiting simple en memoria para WS messages
_ws_message_limiter: dict[str, list[float]] = {}
_WS_MAX_MSG_PER_SEC = 5
_WS_LIMIT_WINDOW = 5  # segundos


def _check_ws_rate_limit(user_id: str) -> bool:
    """Devuelve True si el usuario puede enviar el mensaje."""
    import time
    now = time.time()
    timestamps = _ws_message_limiter.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < _WS_LIMIT_WINDOW]
    if len(timestamps) >= _WS_MAX_MSG_PER_SEC:
        return False
    if not timestamps and user_id in _ws_message_limiter:
        del _ws_message_limiter[user_id]
    timestamps.append(now)
    _ws_message_limiter[user_id] = timestamps
    return True


async def _handle_chat_message(user_id_str: str, msg: dict) -> None:
    room_id_str = msg.get("room_id", "").strip()
    content = msg.get("content", "").strip()[:2000]
    if not room_id_str or not content:
        return

    try:
        room_id = uuid.UUID(room_id_str)
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        return

    from app.models.chat import ChatMessage, ChatMention, ChatRoom, ChatRoomMember
    from app.models.user import User
    from app.services.database import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        room = await db.get(ChatRoom, room_id)
        if not room:
            return

        # Validar membresía en salas privadas
        if room.is_private:
            member = await db.get(ChatRoomMember, (room_id, user_id))
            if not member:
                logger.warning(f"Usuario {user_id} intentó escribir en sala privada {room_id}")
                return

        user = await db.get(User, user_id)
        if not user:
            return

        message = ChatMessage(room_id=room_id, user_id=user_id, content=content)
        db.add(message)
        await db.commit()
        await db.refresh(message)

        # Crear menciones @usuario si las hay (solo a miembros de sala privada)
        usernames = set(_MENTION_RE.findall(content))
        if usernames:
            user_result = await db.execute(select(User).where(User.username.in_(usernames)))
            for u in user_result.scalars().all():
                if u.id == user_id:
                    continue
                # En sala privada, solo mencionar si es miembro
                if room.is_private:
                    is_member = await db.get(ChatRoomMember, (room_id, u.id))
                    if not is_member:
                        continue
                db.add(ChatMention(
                    room_id=room_id,
                    message_id=message.id,
                    user_id=u.id,
                    mentioned_by=user_id,
                ))
            await db.commit()

        # Obtener miembros de la sala para broadcast restringido
        if room.is_private:
            members_result = await db.execute(
                select(ChatRoomMember.user_id).where(ChatRoomMember.room_id == room_id)
            )
            target_user_ids = {str(mid) for mid in members_result.scalars().all()}
            # Incluir al creador/admin aunque no esté en members
            target_user_ids.add(str(room.created_by))
        else:
            target_user_ids = None  # broadcast a todos

        await ws_manager.broadcast_chat_message({
            "type": "chat_message",
            "room_id": room_id_str,
            "message_id": str(message.id),
            "user_id": user_id_str,
            "username": user.username,
            "content": content,
            "created_at": message.created_at.isoformat(),
        }, target_user_ids=target_user_ids)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(None, description="JWT access token (legacy — prefer handshake)"),
):
    """
    Handshake de WebSocket:
      1. Conectar sin auth (o con token legacy en query param)
      2. Si no hay token legacy, esperar primer mensaje: {type: "auth", token: "..."}
      3. Validar token y aceptar/rechazar
    """
    await websocket.accept()

    user: User | None = None
    user_id_str: str | None = None

    # ── Modo legacy: token en query param ──────────────────────
    if token:
        user = await _get_user_from_token(token)

    # ── Modo handshake: esperar mensaje de auth ────────────────
    if not user:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            msg = json.loads(raw)
            if msg.get("type") == "auth":
                user = await _get_user_from_token(msg.get("token", ""))
            if not user:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        except (asyncio.TimeoutError, json.JSONDecodeError):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    # Rechazar roles no autorizados en producción
    if user.role not in ("rol1", "moderator", "admin"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id_str = str(user.id)
    await ws_manager.connect(websocket, user_id_str)

    # ── Suscribir a price updates de los símbolos del usuario ──
    try:
        symbols = await _get_user_active_symbols(user.id)
        if symbols:
            ws_manager.subscribe_symbols(websocket, symbols)
            logger.debug(f"WS user={user_id_str} suscrito a {len(symbols)} símbolos")
    except Exception as exc:
        logger.warning(f"WS error obteniendo símbolos de user={user_id_str}: {exc}")

    error_count = 0
    _MAX_WS_ERRORS = 10

    try:
        while True:
            data = await websocket.receive_text()

            # Límite de tamaño de payload (10 KB)
            if len(data.encode("utf-8")) > 10_240:
                logger.warning(f"WS payload excede 10KB de user={user_id_str}")
                error_count += 1
                if error_count >= _MAX_WS_ERRORS:
                    logger.warning(f"WS desconectando user={user_id_str} por demasiados errores")
                    break
                continue

            if not _check_ws_rate_limit(user_id_str):
                logger.warning(f"WS rate limit excedido por user={user_id_str}")
                error_count += 1
                if error_count >= _MAX_WS_ERRORS:
                    logger.warning(f"WS desconectando user={user_id_str} por demasiados errores")
                    break
                continue

            try:
                msg = json.loads(data)
                if msg.get("type") == "chat_message":
                    if user.role == "rol1":
                        logger.warning(f"WS user={user_id_str} con rol rol1 intentó enviar mensaje de chat")
                    else:
                        await _handle_chat_message(user_id_str, msg)
                error_count = max(0, error_count - 1)  # reducir contador en mensajes válidos
            except json.JSONDecodeError:
                logger.warning(f"WS mensaje JSON inválido de user={user_id_str}")
                error_count += 1
                if error_count >= _MAX_WS_ERRORS:
                    logger.warning(f"WS desconectando user={user_id_str} por demasiados errores")
                    break
            except Exception:
                logger.exception("WS error handling message")
                error_count += 1
                if error_count >= _MAX_WS_ERRORS:
                    logger.warning(f"WS desconectando user={user_id_str} por demasiados errores")
                    break
    except WebSocketDisconnect:
        pass
    finally:
        if user_id_str:
            ws_manager.disconnect(websocket, user_id_str)
