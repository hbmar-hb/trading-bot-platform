import base64
import io
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    TwoFactorLoginRequest,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
    UserProfileUpdateRequest,
    UserResponse,
    VerifyEmailRequest,
)
from app.core.rate_limiter import login_limiter, register_limiter
from app.services.cache import (
    delete_email_verification_token,
    delete_password_reset_token,
    get_email_verification_user,
    get_password_reset_user,
    set_email_verification_token,
    set_password_reset_token,
)
from app.services.database import get_db
from app.services.email_service import send_password_reset_email, send_verification_email
from config.settings import settings
import asyncio

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── Helpers ─────────────────────────────────────────────────

def _create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "type": "access"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _create_refresh_token_value() -> str:
    return str(uuid.uuid4())


def _create_temp_token(user_id: uuid.UUID) -> str:
    """Token de corta duración para el paso intermedio de 2FA (5 min)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "type": "2fa_pending"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _decode_temp_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "2fa_pending":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")
        return uuid.UUID(payload["sub"])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token 2FA expirado o inválido")


async def _issue_tokens(db: AsyncSession, user: User) -> TokenResponse:
    """Revoca tokens anteriores y emite nuevos access + refresh."""
    old_tokens = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked == False,  # noqa: E712
        )
    )
    for token in old_tokens.scalars():
        token.revoked = True

    refresh_value = _create_refresh_token_value()
    db.add(RefreshToken(
        user_id=user.id,
        token=refresh_value,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    ))
    await db.commit()

    return TokenResponse(
        access_token=_create_access_token(user.id),
        refresh_token=refresh_value,
    )


# ─── Login ───────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    login_limiter.check(data.username)
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()

    if not user or not pwd_context.verify(data.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas")

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usuario desactivado")

    if settings.require_email_verification and not user.email_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Email no verificado. Revisa tu bandeja de entrada o solicita un nuevo enlace de verificaci��n.")

    # Si tiene 2FA activo → devolver temp_token para el segundo paso
    if user.totp_enabled:
        return LoginResponse(
            requires_2fa=True,
            temp_token=_create_temp_token(user.id),
        )

    # Sin 2FA → tokens completos
    tokens = await _issue_tokens(db, user)
    return LoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        must_change_password=user.must_change_password,
    )


@router.post("/2fa/login", response_model=TokenResponse)
async def login_2fa(data: TwoFactorLoginRequest, db: AsyncSession = Depends(get_db)):
    """Segundo paso del login cuando 2FA está activo."""
    user_id = _decode_temp_token(data.temp_token)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "2FA no configurado")

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(data.totp_code, valid_window=1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Código 2FA inválido")

    return await _issue_tokens(db, user)


# ─── Refresh ─────────────────────────────────────────────────

@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_token(data: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token == data.refresh_token)
    )
    token_record = result.scalar_one_or_none()

    if not token_record or not token_record.is_valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token inválido o expirado")

    token_record.revoked = True
    await db.commit()

    return AccessTokenResponse(access_token=_create_access_token(token_record.user_id))


# ─── Perfil ──────────────────────────────────────────────────

@router.get("/me", response_model=UserResponse)
async def get_me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    return user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    data: UserProfileUpdateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

    if data.telegram_chat_id is not None:
        user.telegram_chat_id = data.telegram_chat_id.strip() if data.telegram_chat_id.strip() else None
    if data.notify_on_open is not None:
        user.notify_on_open = data.notify_on_open
    if data.notify_on_partial is not None:
        user.notify_on_partial = data.notify_on_partial
    if data.notify_on_close is not None:
        user.notify_on_close = data.notify_on_close
    if data.chat_bg_color is not None:
        user.chat_bg_color = data.chat_bg_color
    if data.chat_bg_shape is not None:
        user.chat_bg_shape = data.chat_bg_shape
    if data.chat_font_family is not None:
        user.chat_font_family = data.chat_font_family
    if data.chat_font_size is not None:
        user.chat_font_size = data.chat_font_size
    if data.chat_font_color is not None:
        user.chat_font_color = data.chat_font_color

    await db.commit()
    await db.refresh(user)
    return user


@router.post("/test-telegram", status_code=status.HTTP_204_NO_CONTENT)
async def test_telegram(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Envía un mensaje de prueba al chat de Telegram del usuario."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.telegram_chat_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No tienes configurado un chat ID de Telegram")

    from app.services.notifier import send_telegram_sync
    send_telegram_sync(
        f"✅ <b>Test de notificaciones</b>\n"
        f"Hola {user.username}, las notificaciones de Trading Bot Platform están configuradas correctamente.",
        chat_id=user.telegram_chat_id,
    )


# ─── Contraseña ──────────────────────────────────────────────

@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: ChangePasswordRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not pwd_context.verify(data.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Contraseña actual incorrecta")

    user.hashed_password = pwd_context.hash(data.new_password)
    user.must_change_password = False
    await db.commit()


# ─── 2FA Setup ───────────────────────────────────────────────

@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Genera un nuevo secret TOTP y devuelve el QR para escanearlo."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=user.username, issuer_name="Trading Bot Platform")

    # Generar QR como base64
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # Guardar secret (aún no activado — se activa al verificar)
    user.totp_secret = secret
    await db.commit()

    return TwoFactorSetupResponse(secret=secret, qr_uri=uri, qr_image=qr_b64)


@router.post("/2fa/verify", status_code=status.HTTP_204_NO_CONTENT)
async def verify_2fa(
    data: TwoFactorVerifyRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Confirma el código TOTP y activa el 2FA."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Primero genera el QR con /2fa/setup")

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(data.totp_code, valid_window=1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Código incorrecto — escanea el QR de nuevo")

    user.totp_enabled = True
    await db.commit()


@router.post("/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_2fa(
    data: TwoFactorVerifyRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Desactiva el 2FA — requiere código TOTP válido para confirmar."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El 2FA no está activo")

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(data.totp_code, valid_window=1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Código incorrecto")

    user.totp_enabled = False
    user.totp_secret = None
    await db.commit()


# ─── Registro ────────────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    register_limiter.check(data.username)
    if not settings.allow_registration:
        existing = await db.execute(select(User).limit(1))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Registro deshabilitado")

    result = await db.execute(
        select(User).where(
            (User.username == data.username) | (User.email == data.email)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Usuario o email ya existe")

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=pwd_context.hash(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Enviar email de verificaci��n si el servicio de email estǭ configurado
    if settings.email_from:
        token = str(uuid.uuid4())
        set_email_verification_token(str(user.id), token)
        verify_url = f"{settings.frontend_url}/verify-email?token={token}"
        await asyncio.to_thread(send_verification_email, user.email, verify_url)

    return user



@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user:
        return None

    token = str(uuid.uuid4())
    set_password_reset_token(str(user.id), token)
    reset_url = f"{settings.frontend_url}/reset-password?token={token}"
    await asyncio.to_thread(send_password_reset_email, user.email, reset_url)
    return None


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    user_id = get_password_reset_user(data.token)
    if not user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Token invalido o expirado")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

    user.hashed_password = pwd_context.hash(data.new_password)
    delete_password_reset_token(data.token)
    await db.commit()
    return None


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(data: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    user_id = get_email_verification_user(data.token)
    if not user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Token invalido o expirado")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

    user.email_verified = True
    delete_email_verification_token(data.token)
    await db.commit()
    return None


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
async def resend_verification(data: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or user.email_verified:
        return None

    token = str(uuid.uuid4())
    set_email_verification_token(str(user.id), token)
    verify_url = f"{settings.frontend_url}/verify-email?token={token}"
    await asyncio.to_thread(send_verification_email, user.email, verify_url)
    return None
