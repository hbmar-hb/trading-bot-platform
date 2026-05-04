"""
Crea la instancia correcta de exchange a partir de un ExchangeAccount o PaperBalance.
Desencripta las credenciales en el momento de la creación.
"""
from decimal import Decimal

from app.exchanges.base import BaseExchange
from app.exchanges.bingx import BingXExchange
from app.exchanges.bitunix import BitunixExchange
from app.exchanges.paper import PaperExchange
from app.models.exchange_account import ExchangeAccount
from app.models.paper_balance import PaperBalance
from app.utils.crypto import decrypt

SUPPORTED_EXCHANGES = ("bingx", "bitunix", "paper")


def create_exchange(account: ExchangeAccount, testnet: bool = False) -> BaseExchange:
    """
    Devuelve un cliente de exchange listo para usar.

    Las credenciales se desencriptan aquí — nunca se almacenan
    en texto plano fuera de este contexto.

    El caller es responsable de llamar await exchange.close()
    cuando ya no necesite el cliente.
    """
    api_key = decrypt(account.api_key_encrypted)
    secret  = decrypt(account.secret_encrypted)

    match account.exchange:
        case "bingx":
            return BingXExchange(api_key, secret, testnet=testnet)
        case "bitunix":
            return BitunixExchange(api_key, secret, testnet=testnet)
        case _:
            raise ValueError(
                f"Exchange '{account.exchange}' no soportado. "
                f"Exchanges disponibles: {SUPPORTED_EXCHANGES}"
            )


def create_paper_exchange(paper_balance: PaperBalance) -> PaperExchange:
    """
    Devuelve un cliente de Paper Trading.
    
    Args:
        paper_balance: Instancia de PaperBalance con la configuración
        
    Returns:
        PaperExchange configurado con el balance inicial
    """
    return PaperExchange(
        account_id=paper_balance.account_id,
        initial_balance=paper_balance.initial_balance
    )


def create_exchange_from_bot(bot) -> BaseExchange:
    """
    Crea el exchange apropiado para un bot.
    
    Si el bot usa una cuenta paper, crea PaperExchange.
    Si usa una cuenta real, crea el exchange correspondiente.
    
    Args:
        bot: Instancia de BotConfig con su exchange_account cargado
        
    Returns:
        Instancia de BaseExchange (real o paper)
    """
    # Verificar si es paper trading
    if hasattr(bot, 'is_paper_trading') and bot.is_paper_trading:
        # Para paper trading, necesitamos el PaperBalance asociado
        # Esto se maneja diferente - el paper_id estaría en el bot
        raise NotImplementedError("Paper trading requiere configuración específica")
    
    # Exchange real
    if not bot.exchange_account:
        raise ValueError("Bot no tiene exchange_account asignado")
        
    return create_exchange(bot.exchange_account)
