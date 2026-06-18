"""
Dependencias reutilizables para inyectar en las rutas de FastAPI.
"""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.cache import is_access_token_blacklisted
from app.services.database import get_db
from config.settings import settings
from loguru import logger

security = HTTPBearer()


def _verify_token(token: str) -> dict:
    """Decode and validate the access token, logging the exact failure reason."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
        )
    except JWTError as exc:
        logger.warning(f"[auth] JWT decode failed: {exc}")
        raise credentials_exception

    user_id: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")

    if user_id is None or payload.get("type") != "access":
        logger.warning(f"[auth] JWT missing sub or invalid type: {payload.get('type')}")
        raise credentials_exception

    token_issuer = payload.get("iss")
    if token_issuer != settings.jwt_issuer:
        logger.warning(
            f"[auth] JWT issuer mismatch: token={token_issuer!r} expected={settings.jwt_issuer!r}"
        )
        raise credentials_exception

    return payload


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> uuid.UUID:
    """
    Valida el JWT del header Authorization y devuelve el user_id.
    Úsala como dependencia en cualquier ruta protegida:

        @router.get("/bots")
        async def get_bots(user_id: uuid.UUID = Depends(get_current_user_id)):
            ...
    """
    token = credentials.credentials
    payload = _verify_token(token)
    user_id: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")
    if jti and await is_access_token_blacklisted(jti):
        logger.warning(f"[auth] JWT blacklisted jti={jti}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return uuid.UUID(user_id)
    except ValueError as exc:
        logger.warning(f"[auth] Invalid user_id UUID: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Valida el JWT y retorna el User completo (cualquier rol)."""
    from sqlalchemy import select

    token = credentials.credentials
    payload = _verify_token(token)
    user_id: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")
    if jti and await is_access_token_blacklisted(jti):
        logger.warning(f"[auth] JWT blacklisted jti={jti}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        logger.warning(f"[auth] Invalid user_id UUID: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"[auth] User not found for id={user_uuid}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_moderator_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Valida el JWT y verifica que el usuario tenga rol 'admin' o 'moderator'."""
    from sqlalchemy import select

    token = credentials.credentials
    payload = _verify_token(token)
    user_id: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")
    if jti and await is_access_token_blacklisted(jti):
        logger.warning(f"[auth] JWT blacklisted jti={jti}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        logger.warning(f"[auth] Invalid user_id UUID: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"[auth] User not found for id={user_uuid}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.role not in ("admin", "moderator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de administrador o moderador",
        )
    return user


async def get_current_admin_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Valida el JWT y verifica que el usuario tenga rol 'admin'.
    Retorna el objeto User completo.
    """
    from sqlalchemy import select

    token = credentials.credentials
    payload = _verify_token(token)
    user_id: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")
    if jti and await is_access_token_blacklisted(jti):
        logger.warning(f"[auth] JWT blacklisted jti={jti}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        logger.warning(f"[auth] Invalid user_id UUID: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"[auth] User not found for id={user_uuid}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de administrador",
        )
    return user


async def get_current_authorized_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Valida el JWT y verifica que el usuario tenga un rol autorizado
    para operar en producción: rol1, moderator o admin.
    """
    from sqlalchemy import select

    token = credentials.credentials
    payload = _verify_token(token)
    user_id: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")
    if jti and await is_access_token_blacklisted(jti):
        logger.warning(f"[auth] JWT blacklisted jti={jti}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        logger.warning(f"[auth] Invalid user_id UUID: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"[auth] User not found for id={user_uuid}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.role not in ("rol1", "moderator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Rol no autorizado",
        )
    return user


async def require_authorized_role(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Complemento para endpoints que usan get_current_user_id.
    Carga el usuario y verifica que tenga rol rol1, moderator o admin.
    """
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.role not in ("rol1", "moderator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Rol no autorizado",
        )
    return user


async def require_non_rol1_role(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Complemento para endpoints que usan get_current_user_id y no deben
    ser accesibles por rol1 (pero sí por moderator o admin).
    """
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.role not in ("moderator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de moderador o administrador",
        )
    return user


async def require_2fa_if_enabled(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Valida el JWT y verifica que si el usuario tiene 2FA activo,
    el token incluya el claim two_factor_verified.
    """
    from sqlalchemy import select

    token = credentials.credentials
    payload = _verify_token(token)
    user_id: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")
    if jti and await is_access_token_blacklisted(jti):
        logger.warning(f"[auth] JWT blacklisted jti={jti}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        logger.warning(f"[auth] Invalid user_id UUID: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    two_factor_verified = payload.get("two_factor_verified", False)

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        logger.warning(f"[auth] User not found or inactive for id={user_uuid}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.totp_enabled and not two_factor_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere verificación 2FA",
        )
    return user
