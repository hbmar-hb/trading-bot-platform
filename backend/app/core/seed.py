"""
Crea el usuario admin por defecto si la DB está vacía.
Solo se ejecuta en ENV=development (via lifespan en main.py).

Credenciales por defecto: admin / Admin1234
CAMBIA LA CONTRASEÑA INMEDIATAMENTE tras el primer login.
"""
import uuid

from passlib.context import CryptContext
from sqlalchemy import select

from app.models.user import User
from app.services.database import AsyncSessionLocal

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "Admin1234"   # Mínimo para pasar el validator: 8 chars, 1 upper, 1 digit


async def seed_first_user_if_empty() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).limit(1))
        if result.scalar_one_or_none() is not None:
            return  # Ya hay usuarios, no hacer nada

        user = User(
            id=uuid.uuid4(),
            username=DEFAULT_USERNAME,
            email="admin@tradingbot.local",
            hashed_password=pwd_context.hash(DEFAULT_PASSWORD),
            is_active=True,
        )
        db.add(user)
        await db.commit()

        print("=" * 60)
        print("⚠️  USUARIO ADMIN CREADO POR DEFECTO")
        print(f"   Usuario:    {DEFAULT_USERNAME}")
        print(f"   Contraseña: {DEFAULT_PASSWORD}")
        print("   CAMBIA LA CONTRASEÑA INMEDIATAMENTE")
        print("=" * 60)
