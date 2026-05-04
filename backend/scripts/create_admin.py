#!/usr/bin/env python3
"""
Crea el primer usuario administrador.
La contraseña se solicita de forma segura (no queda en el historial del shell).

Uso:
    python scripts/create_admin.py --username admin
    python scripts/create_admin.py --username admin --email admin@example.com
"""
import argparse
import getpass
import sys
import uuid
from pathlib import Path

# Añadir el directorio backend/ al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_admin(username: str, password: str, email: str) -> bool:
    from app.models.user import User

    engine = create_engine(settings.database_url_sync)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"❌ El usuario '{username}' ya existe")
            return False

        if len(password) < 8:
            print("❌ La contraseña debe tener al menos 8 caracteres")
            return False

        user = User(
            id=uuid.uuid4(),
            username=username,
            email=email,
            hashed_password=pwd_context.hash(password),
            is_active=True,
        )
        db.add(user)
        db.commit()

    print(f"✅ Usuario '{username}' creado")
    print(f"   Email: {email}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Crear usuario administrador")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email",    default=None)
    args = parser.parse_args()

    email = args.email or f"{args.username}@tradingbot.local"

    print(f"\n🔐 Creando usuario: {args.username}")
    password = getpass.getpass("Contraseña: ")
    confirm  = getpass.getpass("Confirmar:  ")

    if not password:
        print("❌ La contraseña no puede estar vacía")
        sys.exit(1)

    if password != confirm:
        print("❌ Las contraseñas no coinciden")
        sys.exit(1)

    success = create_admin(args.username, password, email)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
