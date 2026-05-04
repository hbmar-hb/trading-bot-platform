"""
Gestión de usuarios (admin).
Requiere JWT válido — cualquier usuario autenticado puede gestionar usuarios.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import asyncio

from app.api.dependencies import get_current_admin_user, get_current_user_id
from app.models.user import User
from app.schemas.auth import UserCreate, UserResponse, UserResetPassword, UserUpdate
from app.services.database import get_db
from app.services.email_service import send_welcome_email
from config.settings import settings

router = APIRouter(prefix="/users", tags=["users"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=pwd_context.hash(data.password),
        role=data.role if data.role in ("user", "admin") else "user",
        must_change_password=True,
        telegram_chat_id=data.telegram_chat_id.strip() if data.telegram_chat_id and data.telegram_chat_id.strip() else None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    if settings.email_from:
        await asyncio.to_thread(
            send_welcome_email,
            data.email,
            data.username,
            data.password,
            settings.frontend_url,
        )

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
        # Verificar unicidad del nuevo username
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
        # No permitir desactivarse a uno mismo (ni al admin principal)
        if user_id == current_admin.id and not data.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes desactivar tu propia cuenta")
        user.is_active = data.is_active

    if data.role is not None:
        if data.role in ("user", "admin"):
            user.role = data.role

    if data.telegram_chat_id is not None:
        user.telegram_chat_id = data.telegram_chat_id.strip() if data.telegram_chat_id.strip() else None

    await db.commit()
    await db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: uuid.UUID,
    data: UserResetPassword,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_404(user_id, db)
    user.hashed_password = pwd_context.hash(data.new_password)
    user.must_change_password = True
    await db.commit()

    if settings.email_from:
        await asyncio.to_thread(
            send_welcome_email,
            user.email,
            user.username,
            data.new_password,
            settings.frontend_url,
        )


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
