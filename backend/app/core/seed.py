"""
Crea el usuario admin por defecto si la DB está vacía.
Solo se ejecuta en ENV=development (via lifespan en main.py).

Se genera una contraseña aleatoria segura por única vez.
CAMBIA LA CONTRASEÑA INMEDIATAMENTE tras el primer login.
"""
import secrets
import uuid

from passlib.context import CryptContext
from sqlalchemy import select

from app.models.user import User
from app.services.database import AsyncSessionLocal

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_USERNAME = "admin"


def _generate_secure_password(length: int = 16) -> str:
    """Genera una contraseña aleatoria alfanumérica segura."""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def seed_first_user_if_empty() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).limit(1))
        if result.scalar_one_or_none() is not None:
            return  # Ya hay usuarios, no hacer nada

        password = _generate_secure_password()
        user = User(
            id=uuid.uuid4(),
            username=DEFAULT_USERNAME,
            email="admin@tradingbot.local",
            hashed_password=pwd_context.hash(password),
            is_active=True,
            role="admin",
        )
        db.add(user)
        await db.commit()

        print("=" * 60)
        print("⚠️  USUARIO ADMIN CREADO POR DEFECTO")
        print(f"   Usuario:    {DEFAULT_USERNAME}")
        print(f"   Contraseña: {password}")
        print("   CAMBIA LA CONTRASEÑA INMEDIATAMENTE")
        print("=" * 60)
