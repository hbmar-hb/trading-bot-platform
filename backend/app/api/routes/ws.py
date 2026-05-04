import json
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt

from app.api.websocket.manager import ws_manager
from config.settings import settings

router = APIRouter(tags=["websocket"])


def _get_user_id_from_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        sub = payload.get("sub")
        return uuid.UUID(sub) if sub else None
    except (JWTError, ValueError):
        return None


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

    from app.models.chat import ChatMessage, ChatRoom
    from app.models.user import User
    from app.services.database import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        room_check = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
        if not room_check.scalar_one_or_none():
            return

        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return

        message = ChatMessage(room_id=room_id, user_id=user_id, content=content)
        db.add(message)
        await db.commit()
        await db.refresh(message)

        await ws_manager.broadcast_to_all({
            "type": "chat_message",
            "room_id": room_id_str,
            "message_id": str(message.id),
            "user_id": user_id_str,
            "username": user.username,
            "content": content,
            "created_at": message.created_at.isoformat(),
        })


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    user_id = _get_user_id_from_token(token)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id_str = str(user_id)
    await ws_manager.connect(websocket, user_id_str)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "chat_message":
                    await _handle_chat_message(user_id_str, msg)
            except (json.JSONDecodeError, Exception):
                pass

    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(websocket, user_id_str)
