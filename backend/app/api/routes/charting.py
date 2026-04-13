"""Endpoints para TradingView Charting Library"""
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id
from app.exchanges.factory import ExchangeFactory
from app.services.database import get_db
from app.models.exchange_account import ExchangeAccount

router = APIRouter(prefix="/charting", tags=["charting"])


@router.get("/history")
async def get_chart_history(
    symbol: str,
    resolution: str,  # 1, 5, 15, 60, 240, D, W, M
    from_time: int,   # Unix timestamp
    to_time: int,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Datos históricos de velas para el gráfico."""
    # Obtener cuenta de exchange por defecto
    result = await db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.user_id == user_id, ExchangeAccount.is_active == True)
        .limit(1)
    )
    account = result.scalar_one_or_none()
    
    if not account:
        return {"s": "no_data", "errmsg": "No exchange account"}
    
    # Convertir timeframe
    timeframe_map = {
        '1': '1m', '5': '5m', '15': '15m', '30': '30m',
        '60': '1h', '240': '4h', 'D': '1d', 'W': '1w', 'M': '1M'
    }
    timeframe = timeframe_map.get(resolution, '1h')
    
    # Obtener datos del exchange
    exchange = ExchangeFactory.create(account.exchange, {
        'api_key': account.api_key,
        'api_secret': account.api_secret,
    })
    
    try:
        klines = await exchange.get_klines(
            symbol=symbol,
            timeframe=timeframe,
            limit=1000,
            since=from_time * 1000
        )
        
        if not klines:
            return {"s": "no_data", "errmsg": "No data available"}
        
        # Formato UDF (Universal Data Feed) de TradingView
        return {
            "s": "ok",
            "t": [int(k[0] / 1000) for k in klines],  # timestamps
            "o": [float(k[1]) for k in klines],       # open
            "h": [float(k[2]) for k in klines],       # high
            "l": [float(k[3]) for k in klines],       # low
            "c": [float(k[4]) for k in klines],       # close
            "v": [float(k[5]) for k in klines],       # volume
        }
    except Exception as e:
        return {"s": "error", "errmsg": str(e)}


@router.get("/config")
async def get_chart_config(
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Configuración del gráfico para el usuario."""
    return {
        "supports_search": True,
        "supports_group_request": False,
        "supports_marks": True,
        "supports_timescale_marks": True,
        "supports_time": True,
        "exchanges": [
            {"value": "BingX", "name": "BingX", "desc": "BingX Futures"},
        ],
        "symbols_types": [
            {"name": "Crypto", "value": "crypto"},
        ],
        "supported_resolutions": ["1", "5", "15", "30", "60", "240", "D", "W", "M"],
    }


@router.get("/symbols")
async def search_symbols(
    query: str = Query(default=""),
    exchange: str = Query(default="BingX"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Búsqueda de símbolos disponibles en el exchange."""
    import logging
    logger = logging.getLogger(__name__)
    
    # Lista completa de pares populares como fallback
    POPULAR_SYMBOLS = [
        "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", 
        "DOGE/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT", "LINK/USDT:USDT",
        "DOT/USDT:USDT", "MATIC/USDT:USDT", "LTC/USDT:USDT", "BCH/USDT:USDT",
        "UNI/USDT:USDT", "ATOM/USDT:USDT", "ETC/USDT:USDT", "XLM/USDT:USDT",
        "NEAR/USDT:USDT", "FIL/USDT:USDT", "ALGO/USDT:USDT", "VET/USDT:USDT",
        "ICP/USDT:USDT", "MANA/USDT:USDT", "SAND/USDT:USDT", "AXS/USDT:USDT",
        "THETA/USDT:USDT", "FTM/USDT:USDT", "GRT/USDT:USDT", "CAKE/USDT:USDT",
        "1000PEPE/USDT:USDT", "1000SHIB/USDT:USDT", "1000FLOKI/USDT:USDT",
        "WIF/USDT:USDT", "BONK/USDT:USDT", "FARTCOIN/USDT:USDT", "MOODENG/USDT:USDT",
        "LUNC/USDT:USDT", "PEOPLE/USDT:USDT", "WLD/USDT:USDT", "ARKM/USDT:USDT",
        "JUP/USDT:USDT", "PYTH/USDT:USDT", "SEI/USDT:USDT", "SUI/USDT:USDT",
        "TIA/USDT:USDT", "APT/USDT:USDT", "IMX/USDT:USDT", "OP/USDT:USDT",
        "ARB/USDT:USDT", "STRK/USDT:USDT", "ENA/USDT:USDT", "HYPE/USDT:USDT",
        "ICNT/USDT:USDT", "AI16Z/USDT:USDT", "ZRO/USDT:USDT", "JTO/USDT:USDT",
    ]
    
    # Obtener cuenta del usuario
    result = await db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.user_id == user_id, ExchangeAccount.is_active == True)
        .limit(1)
    )
    account = result.scalar_one_or_none()
    
    symbols = []
    
    if account:
        try:
            # Intentar obtener del exchange
            exchange_client = ExchangeFactory.create(account.exchange, {
                'api_key': account.api_key,
                'api_secret': account.api_secret,
            })
            logger.info(f"Loading markets for {account.exchange}")
            markets = await exchange_client.load_markets()
            logger.info(f"Loaded {len(markets)} markets")
            # Filtrar solo perpetuals de USDT (formato CCXT para BingX es SYMBOL/USDT:USDT)
            symbols = [s for s in markets.keys() if ':USDT' in s]
            symbols.sort()
            logger.info(f"Filtered to {len(symbols)} USDT perpetuals")
        except Exception as e:
            logger.error(f"Error loading markets: {e}", exc_info=True)
            # Fallback a lista popular
            symbols = POPULAR_SYMBOLS
    else:
        logger.warning("No exchange account found, using default symbols")
        # Fallback si no hay cuenta
        symbols = POPULAR_SYMBOLS[:20]
    
    # Si no hay símbolos, usar fallback
    if not symbols:
        logger.warning("No symbols loaded, using fallback")
        symbols = POPULAR_SYMBOLS
    
    # Filtrar por query si se proporciona
    if query:
        symbols = [s for s in symbols if query.upper() in s.upper()]
    
    return [
        {
            "symbol": s,
            "full_name": f"{exchange}:{s}",
            "description": s.replace("/USDT:USDT", "").replace("/USDT", ""),
            "exchange": exchange,
            "type": "crypto",
            "currency_code": "USDT",
        }
        for s in symbols[:100]  # Aumentar a 100 resultados
    ]


@router.post("/trade")
async def place_chart_trade(
    symbol: str,
    side: str,  # buy, sell
    order_type: str = "market",
    quantity: float = None,
    price: float = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Ejecutar orden desde el gráfico."""
    # Integrar con tu sistema de trading existente
    pass
