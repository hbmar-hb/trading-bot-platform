"""
Configuración de Loguru.
Llamar a setup_logging() una vez al arrancar la aplicación.
"""
import re
import sys
from pathlib import Path

from loguru import logger


# Patrones sensibles que se redactan automáticamente en todos los logs
_SENSITIVE_PATTERNS = [
    (re.compile(r'"api_key"\s*:\s*"[^"]*"', re.IGNORECASE), '"api_key":"***"'),
    (re.compile(r'"secret"\s*:\s*"[^"]*"', re.IGNORECASE), '"secret":"***"'),
    (re.compile(r'"password"\s*:\s*"[^"]*"', re.IGNORECASE), '"password":"***"'),
    (re.compile(r'"token"\s*:\s*"[^"]*"', re.IGNORECASE), '"token":"***"'),
    (re.compile(r'"authorization"\s*:\s*"[^"]*"', re.IGNORECASE), '"authorization":"***"'),
    (re.compile(r'apikey[=:]\S+', re.IGNORECASE), 'apikey=***'),
    (re.compile(r'secret[=:]\S+', re.IGNORECASE), 'secret=***'),
]


def _redact_patcher(record):
    """Interceptor de Loguru: redacta datos sensibles antes de formatear."""
    msg = record["message"]
    for pattern, replacement in _SENSITIVE_PATTERNS:
        msg = pattern.sub(replacement, msg)
    record["message"] = msg


def setup_logging(debug: bool = False) -> None:
    logger.remove()  # quitar handler por defecto
    logger.configure(patcher=_redact_patcher)

    level = "DEBUG" if debug else "INFO"

    # ── Consola ───────────────────────────────────────────────
    logger.add(
        sys.stdout,
        level=level,
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level:<8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
            "{message}"
        ),
    )

    # ── Fichero rotativo (solo en producción) ─────────────────
    if not debug:
        Path("logs").mkdir(exist_ok=True)
        logger.add(
            "logs/trading_bot.log",
            level="INFO",
            rotation="100 MB",
            retention="30 days",
            compression="gz",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} — {message}",
        )

    logger.info(f"Logging configurado — nivel: {level}")
