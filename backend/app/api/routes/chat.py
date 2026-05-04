"""Chat API: salas, mensajes y GIFs."""
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_admin_user, get_current_user_id
from app.models.chat import ChatMessage, ChatRoom
from app.models.user import User
from app.schemas.chat import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatRoomCreate,
    ChatRoomResponse,
)
from app.services.database import get_db
from config.settings import settings

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/rooms", response_model=list[ChatRoomResponse])
async def list_rooms(
    _: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ChatRoom).order_by(ChatRoom.created_at))
    return result.scalars().all()


@router.post("/rooms", response_model=ChatRoomResponse, status_code=status.HTTP_201_CREATED)
async def create_room(
    data: ChatRoomCreate,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(ChatRoom).where(ChatRoom.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una sala con ese nombre")

    room = ChatRoom(name=data.name, description=data.description, created_by=admin.id)
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    room_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sala no encontrada")
    await db.delete(room)
    await db.commit()


@router.get("/rooms/{room_id}/messages", response_model=list[ChatMessageResponse])
async def get_messages(
    room_id: uuid.UUID,
    limit: int = 50,
    _: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatMessage, User.username)
        .join(User, ChatMessage.user_id == User.id)
        .where(ChatMessage.room_id == room_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = result.all()
    return [
        ChatMessageResponse(
            id=msg.id,
            room_id=msg.room_id,
            user_id=msg.user_id,
            username=username,
            content=msg.content,
            created_at=msg.created_at,
            updated_at=msg.updated_at,
        )
        for msg, username in reversed(rows)
    ]


@router.post("/messages", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    data: ChatMessageCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    room = await db.get(ChatRoom, data.room_id)
    if not room:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sala no encontrada")

    msg = ChatMessage(room_id=data.room_id, user_id=user_id, content=data.content)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    user_result = await db.execute(select(User.username).where(User.id == user_id))
    username = user_result.scalar_one()

    return ChatMessageResponse(
        id=msg.id,
        room_id=msg.room_id,
        user_id=msg.user_id,
        username=username,
        content=msg.content,
        created_at=msg.created_at,
        updated_at=msg.updated_at,
    )


@router.get("/gifs")
async def search_gifs(
    q: str = Query(""),
    _: uuid.UUID = Depends(get_current_user_id),
):
    if not settings.giphy_api_key:
        return {"data": [], "enabled": False}

    endpoint = "https://api.giphy.com/v1/gifs/trending" if not q.strip() else "https://api.giphy.com/v1/gifs/search"
    params = {"api_key": settings.giphy_api_key, "limit": 24, "rating": "g"}
    if q.strip():
        params["q"] = q.strip()

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(endpoint, params=params)
        resp.raise_for_status()
        raw = resp.json()

    gifs = [
        {
            "id": g["id"],
            "title": g["title"],
            "preview": g["images"]["fixed_height_small"]["url"],
            "url": g["images"]["fixed_height"]["url"],
            "original": g["images"]["original"]["url"],
        }
        for g in raw.get("data", [])
    ]
    return {"data": gifs, "enabled": True}
