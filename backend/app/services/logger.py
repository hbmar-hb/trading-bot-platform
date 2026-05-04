"""
Configuración de Loguru.
Llamar a setup_logging() una vez al arrancar la aplicación.
"""
import sys
from pathlib import Path

from loguru import logger


def setup_logging(debug: bool = False) -> None:
    logger.remove()  # quitar handler por defecto

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
