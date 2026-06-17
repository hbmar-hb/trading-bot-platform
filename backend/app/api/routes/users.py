"""
Gestión de usuarios (admin).
Los admins crean usuarios — el sistema envía el link de establecimiento
de contraseña por email. Ningún admin puede ver ni definir contraseñas.
"""
import asyncio
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_admin_user
from app.models.user import User
from app.schemas.auth import UserCreate, UserResponse, UserUpdate
from app.services.cache import set_password_reset_token
from app.services.database import get_db
from app.services.email_service import send_password_reset_email, send_welcome_email
from config.settings import settings

# WebSocket manager para consultar usuarios conectados
from app.api.websocket.manager import ws_manager

router = APIRouter(prefix="/users", tags=["users"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

VALID_ROLES = ("rol1", "moderator", "admin")


async def _get_user_or_404(user_id: uuid.UUID, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    return user


@router.get("", response_model=list[UserResponse])
async def list_users(
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at))
    return result.scalars().all()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(User).where(
            (User.username == data.username) | (User.email == data.email)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Usuario o email ya existe")

    # Contraseña temporal aleatoria — el usuario la definirá por email
    temp_password = secrets.token_urlsafe(32)

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=pwd_context.hash(temp_password),
        role=data.role if data.role in VALID_ROLES else "rol1",
        telegram_chat_id=data.telegram_chat_id.strip() if data.telegram_chat_id and data.telegram_chat_id.strip() else None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Generar token de establecimiento de contraseña y enviarlo por email
    token = str(uuid.uuid4())
    set_password_reset_token(str(user.id), token)
    reset_url = f"{settings.frontend_url}/reset-password?token={token}"
    await asyncio.to_thread(send_welcome_email, user.email, user.username, reset_url)

    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_404(user_id, db)

    if data.username is not None:
        dup = await db.execute(
            select(User).where(User.username == data.username, User.id != user_id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status.HTTP_409_CONFLICT, "Ese nombre de usuario ya está en uso")
        user.username = data.username

    if data.email is not None:
        dup = await db.execute(
            select(User).where(User.email == data.email, User.id != user_id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status.HTTP_409_CONFLICT, "Ese email ya está en uso")
        user.email = data.email

    if data.is_active is not None:
        if user_id == current_admin.id and not data.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes desactivar tu propia cuenta")
        user.is_active = data.is_active

    if data.role is not None:
        if data.role in VALID_ROLES:
            user.role = data.role

    if data.telegram_chat_id is not None:
        user.telegram_chat_id = data.telegram_chat_id.strip() if data.telegram_chat_id.strip() else None

    await db.commit()
    await db.refresh(user)
    return user


@router.post("/{user_id}/send-reset-email", status_code=status.HTTP_204_NO_CONTENT)
async def send_reset_email(
    user_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """El admin dispara un email de restablecimiento de contraseña al usuario.
    Nunca puede ver ni establecer la contraseña directamente."""
    user = await _get_user_or_404(user_id, db)
    token = str(uuid.uuid4())
    set_password_reset_token(str(user.id), token)
    reset_url = f"{settings.frontend_url}/reset-password?token={token}"
    await asyncio.to_thread(send_password_reset_email, user.email, reset_url)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes eliminar tu propia cuenta")

    user = await _get_user_or_404(user_id, db)
    await db.delete(user)
    await db.commit()


@router.get("/online-status")
async def online_status(
    _: User = Depends(get_current_admin_user),
):
    """Devuelve el número de usuarios actualmente conectados vía WebSocket."""
    online_ids = ws_manager.get_online_user_ids()
    return {
        "total_connected": len(online_ids),
    }
