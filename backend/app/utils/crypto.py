"""
Encriptación simétrica (Fernet) para API keys de exchanges almacenadas en DB.

Uso:
    from app.utils.crypto import encrypt, decrypt

    encrypted = encrypt("mi_api_key_de_bingx")
    original  = decrypt(encrypted)

Generar ENCRYPTION_KEY:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from cryptography.fernet import Fernet, InvalidToken

from config.settings import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Instancia Fernet singleton (inicialización lazy para no fallar en import)."""
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.encryption_key.encode())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encripta un string y devuelve el token como string."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Desencripta un token. Lanza ValueError si el token es inválido o fue alterado."""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError("Token de encriptación inválido o clave incorrecta") from e
