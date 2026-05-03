import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_admin_user, get_current_user_id
from app.models.chat import ChatMessage, ChatRoom
from app.models.user import User
from app.schemas.chat import ChatMessageResponse, ChatRoomCreate, ChatRoomResponse
from app.services.database import get_db

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
        )
        for msg, username in reversed(rows)
    ]
