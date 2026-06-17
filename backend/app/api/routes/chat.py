"""
Chat API: salas, mensajes y GIFs.
Roles:
  admin     — crea/elimina cualquier canal; crea canales privados; gestiona miembros
  moderator — crea/elimina canales públicos
  rol1      — no tiene acceso al chat
"""
import re
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_moderator_user
from app.models.chat import ChatMention, ChatMessage, ChatRoom, ChatRoomMember
from app.models.user import User
from app.schemas.chat import (
    ChatGifSearch,
    ChatMentionResponse,
    ChatMessageCreate,
    ChatMessageResponse,
    ChatRoomCreate,
    ChatRoomMemberAdd,
    ChatRoomResponse,
)
from app.services.database import get_db
from config.settings import settings


_MENTION_RE = re.compile(r"@([a-zA-Z0-9_]+)")

router = APIRouter(prefix="/chat", tags=["chat"])


def _display_name(username: str, role: str) -> str:
    if role == "admin":
        return f"[{username}_admin]"
    if role == "moderator":
        return f"[{username}_moderador]"
    return f"[{username}]"


async def _assert_room_access(room: ChatRoom, user: User, db: AsyncSession) -> None:
    """Lanza 403 si el usuario no puede ver una sala privada."""
    if not room.is_private or user.role == "admin":
        return
    member = await db.get(ChatRoomMember, (room.id, user.id))
    if not member:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a esta sala privada")


@router.get("/rooms", response_model=list[ChatRoomResponse])
async def list_rooms(
    current_user: User = Depends(get_current_moderator_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ChatRoom).order_by(ChatRoom.created_at.desc()))
    rooms = result.scalars().all()

    if current_user.role == "admin":
        return rooms

    # Obtener IDs de salas privadas donde el usuario es miembro
    member_result = await db.execute(
        select(ChatRoomMember.room_id).where(ChatRoomMember.user_id == current_user.id)
    )
    member_ids = set(member_result.scalars().all())

    return [r for r in rooms if not r.is_private or r.id in member_ids]


@router.post("/rooms", response_model=ChatRoomResponse, status_code=status.HTTP_201_CREATED)
async def create_room(
    data: ChatRoomCreate,
    current_user: User = Depends(get_current_moderator_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role not in ("admin", "moderator"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo admin y moderadores pueden crear canales")

    if data.is_private and current_user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo los admin pueden crear canales privados")

    existing = await db.execute(select(ChatRoom).where(ChatRoom.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una sala con ese nombre")

    room = ChatRoom(
        name=data.name,
        description=data.description,
        created_by=current_user.id,
        is_private=data.is_private,
    )
    db.add(room)
    await db.flush()

    if data.is_private:
        # Creador siempre es miembro
        db.add(ChatRoomMember(room_id=room.id, user_id=current_user.id))
        for mid in data.member_ids:
            if mid != current_user.id:
                # Verificar que el usuario existe
                u = await db.get(User, mid)
                if u:
                    db.add(ChatRoomMember(room_id=room.id, user_id=mid))

    await db.commit()
    await db.refresh(room)
    return room


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    room_id: uuid.UUID,
    current_user: User = Depends(get_current_moderator_user),
    db: AsyncSession = Depends(get_db),
):
    room = await db.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sala no encontrada")

    # Admin puede eliminar cualquier sala; moderador puede eliminar las públicas
    if current_user.role == "admin":
        pass
    elif current_user.role == "moderator" and not room.is_private:
        pass
    elif room.created_by == current_user.id and not room.is_private:
        pass
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No puedes eliminar esta sala")

    await db.delete(room)
    await db.commit()


# ── Gestión de miembros (admin only, salas privadas) ─────────────────────────

@router.post("/rooms/{room_id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def add_member(
    room_id: uuid.UUID,
    data: ChatRoomMemberAdd,
    current_user: User = Depends(get_current_moderator_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo los admin pueden gestionar miembros")

    room = await db.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sala no encontrada")
    if not room.is_private:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Esta sala es pública")

    user = await db.get(User, data.user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

    existing = await db.get(ChatRoomMember, (room_id, data.user_id))
    if existing:
        return  # ya es miembro

    db.add(ChatRoomMember(room_id=room_id, user_id=data.user_id))
    await db.commit()


@router.delete("/rooms/{room_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    room_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_moderator_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo los admin pueden gestionar miembros")

    room = await db.get(ChatRoom, room_id)
    if not room or not room.is_private:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sala privada no encontrada")

    member = await db.get(ChatRoomMember, (room_id, user_id))
    if member:
        await db.delete(member)
        await db.commit()


# ── Mensajes ──────────────────────────────────────────────────────────────────

@router.get("/rooms/{room_id}/messages", response_model=list[ChatMessageResponse])
async def list_messages(
    room_id: uuid.UUID,
    limit: int = 50,
    current_user: User = Depends(get_current_moderator_user),
    db: AsyncSession = Depends(get_db),
):
    room = await db.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sala no encontrada")

    await _assert_room_access(room, current_user, db)

    result = await db.execute(
        select(ChatMessage, User.username, User.role)
        .join(User, ChatMessage.user_id == User.id)
        .where(ChatMessage.room_id == room_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
    )
    rows = result.all()
    rows.reverse()

    return [
        {
            "id": msg.id,
            "room_id": msg.room_id,
            "user_id": msg.user_id,
            "username": _display_name(username, role),
            "role": role,
            "content": msg.content,
            "created_at": msg.created_at,
            "updated_at": msg.updated_at,
        }
        for msg, username, role in rows
    ]


@router.post("/messages", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    data: ChatMessageCreate,
    current_user: User = Depends(get_current_moderator_user),
    db: AsyncSession = Depends(get_db),
):
    room = await db.get(ChatRoom, data.room_id)
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sala no encontrada")

    await _assert_room_access(room, current_user, db)

    msg = ChatMessage(
        room_id=data.room_id,
        user_id=current_user.id,
        content=data.content,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    await _create_mentions(db, msg.room_id, msg.id, msg.content, current_user.id)
    await db.commit()

    return {
        "id": msg.id,
        "room_id": msg.room_id,
        "user_id": msg.user_id,
        "username": _display_name(current_user.username, current_user.role),
        "role": current_user.role,
        "content": msg.content,
        "created_at": msg.created_at,
        "updated_at": msg.updated_at,
    }


async def _create_mentions(db: AsyncSession, room_id: uuid.UUID, message_id: uuid.UUID, content: str, mentioned_by: uuid.UUID) -> None:
    """Detecta @username en el contenido y crea registros de mencion."""
    usernames = set(_MENTION_RE.findall(content))
    if not usernames:
        return

    result = await db.execute(select(User).where(User.username.in_(usernames)))
    users = result.scalars().all()
    for u in users:
        if u.id == mentioned_by:
            continue
        db.add(ChatMention(
            room_id=room_id,
            message_id=message_id,
            user_id=u.id,
            mentioned_by=mentioned_by,
        ))


# ── Menciones ─────────────────────────────────────────────────────────────────

@router.get("/mentions", response_model=list[ChatMentionResponse])
async def list_mentions(
    current_user: User = Depends(get_current_moderator_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatMention, User.username)
        .join(User, ChatMention.mentioned_by == User.id)
        .where(ChatMention.user_id == current_user.id)
        .where(ChatMention.is_read == False)
        .order_by(desc(ChatMention.created_at))
    )
    return [
        {
            "id": m.id,
            "room_id": m.room_id,
            "message_id": m.message_id,
            "user_id": m.user_id,
            "mentioned_by": m.mentioned_by,
            "mentioned_by_username": username,
            "is_read": m.is_read,
            "created_at": m.created_at,
        }
        for m, username in result.all()
    ]


@router.post("/mentions/{mention_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_mention_read(
    mention_id: uuid.UUID,
    current_user: User = Depends(get_current_moderator_user),
    db: AsyncSession = Depends(get_db),
):
    mention = await db.get(ChatMention, mention_id)
    if not mention or mention.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mencion no encontrada")
    mention.is_read = True
    await db.commit()


@router.post("/rooms/{room_id}/mentions/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_room_mentions_read(
    room_id: uuid.UUID,
    current_user: User = Depends(get_current_moderator_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        ChatMention.__table__.update()
        .where(ChatMention.user_id == current_user.id)
        .where(ChatMention.room_id == room_id)
        .where(ChatMention.is_read == False)
        .values(is_read=True)
    )
    await db.commit()


@router.get("/gifs")
async def search_gifs(q: str = ""):
    if not settings.giphy_api_key:
        return {"gifs": [], "note": "GIPHY_API_KEY no configurada"}

    try:
        resp = httpx.get(
            "https://api.giphy.com/v1/gifs/search",
            params={
                "api_key": settings.giphy_api_key,
                "q": q or "trading",
                "limit": 10,
                "rating": "pg-13",
                "lang": "es",
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        gifs = [
            {
                "id": g["id"],
                "url": g["images"]["fixed_height"]["url"],
                "preview": g["images"]["preview_gif"]["url"],
                "title": g.get("title", ""),
            }
            for g in data.get("data", [])
            if "images" in g and "fixed_height" in g["images"]
        ]
        return {"gifs": gifs}
    except Exception:
        return {"gifs": [], "note": "Error consultando Giphy"}
