"""Chart endpoints - Using same logic as markets-by-exchange"""
import ccxt.async_support as ccxt
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import time

from app.api.dependencies import get_current_user_id
from app.exchanges.factory import create_exchange
from app.services.database import get_db
from app.models.exchange_account import ExchangeAccount

router = APIRouter(prefix="/charting", tags=["charting"])

# In-memory cache for symbol lists (TTL 5 min)
_symbols_cache = {}
_SYMBOLS_TTL_SECONDS = 300


def _to_ccxt_symbol(symbol: str) -> str:
    """Convierte formatos nativos de exchange a CCXT."""
    if not symbol:
        return symbol
    # Ya está en formato CCXT
    if "/" in symbol:
        return symbol
    # Quitar sufijo .P de perpetual
    s = symbol.replace(".P", "").replace(".p", "")
    # Intentar separar base/quote por sufijos comunes
    for quote in ["USDT", "USDC", "BTC", "ETH", "USD"]:
        if s.endswith(quote):
            base = s[: -len(quote)]
            return f"{base}/{quote}:{quote}"
    return symbol


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
    symbol = _to_ccxt_symbol(symbol)
    
    # Convertir timeframe (soporta tanto '1h' como '60')
    timeframe_map = {
        '1': '1m', '1m': '1m',
        '5': '5m', '5m': '5m',
        '10': '10m', '10m': '10m',
        '15': '15m', '15m': '15m',
        '30': '30m', '30m': '30m',
        '60': '1h', '1h': '1h',
        '120': '2h', '2h': '2h',
        '240': '4h', '4h': '4h',
        'D': '1d', '1d': '1d',
        'W': '1w', '1w': '1w',
        'M': '1M', '1M': '1M'
    }
    timeframe = timeframe_map.get(resolution, '1h')
    
    # ── Fuente de datos: Binance público (histórico mucho más extenso que BingX) ──
    # No requiere cuenta de exchange — cliente público
    binance = ccxt.binance({'options': {'defaultType': 'swap'}})
    
    async def fetch_binance_pagination(sym, tf, since_ms, to_ts, max_calls=100):
        """Paginar velas desde Binance público."""
        all_candles = []
        current_since = since_ms
        for _ in range(max_calls):
            try:
                ohlcv = await binance.fetch_ohlcv(sym, tf, since=current_since, limit=1000)
            except Exception as e:
                logger = __import__('loguru').logger
                logger.warning(f"Binance pagination error: {e}")
                break
            if not ohlcv:
                break
            batch = [{"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in ohlcv]
            all_candles.extend(batch)
            current_since = (batch[-1]["time"] + 1) * 1000
            if batch[-1]["time"] >= to_ts:
                break
        return all_candles
    
    async def fetch_exchange_pagination(exchange, sym, tf, since_ms, to_ts, max_calls=60):
        """Paginar velas desde el exchange del usuario."""
        all_candles = []
        current_since = since_ms
        for _ in range(max_calls):
            batch = await exchange.get_candles(sym, tf, limit=1000, since=current_since)
            if not batch:
                break
            all_candles.extend(batch)
            current_since = (batch[-1]["time"] + 1) * 1000
            if batch[-1]["time"] >= to_ts:
                break
        return all_candles
    
    try:
        # Intentar Binance primero (histórico extenso, cliente público)
        all_candles = await fetch_binance_pagination(
            symbol, timeframe, from_time * 1000, to_time, max_calls=100
        )
        
        # Fallback al exchange del usuario si Binance no devuelve datos
        if not all_candles:
            # Obtener cuenta de exchange por defecto (solo para fallback)
            result = await db.execute(
                select(ExchangeAccount)
                .where(ExchangeAccount.user_id == user_id, ExchangeAccount.is_active == True)
                .limit(1)
            )
            account = result.scalar_one_or_none()
            
            if account:
                exchange = create_exchange(account)
                all_candles = await fetch_exchange_pagination(
                    exchange, symbol, timeframe, from_time * 1000, to_time, max_calls=60
                )
                await exchange.close()
            else:
                await binance.close()
                return {"s": "no_data", "errmsg": f"Symbol {symbol} not available on Binance and no exchange account configured"}
        
        await binance.close()
        
        if not all_candles:
            return {"s": "no_data", "errmsg": "No data available"}
        
        # Filtrar por rango de tiempo exacto
        filtered_candles = [c for c in all_candles if from_time <= c["time"] <= to_time]
        if not filtered_candles:
            filtered_candles = all_candles
        
        # Formato UDF (Universal Data Feed) de TradingView
        return {
            "s": "ok",
            "t": [c["time"] for c in filtered_candles],
            "o": [c["open"] for c in filtered_candles],
            "h": [c["high"] for c in filtered_candles],
            "l": [c["low"] for c in filtered_candles],
            "c": [c["close"] for c in filtered_candles],
            "v": [c["volume"] for c in filtered_candles],
        }
    except Exception as e:
        await binance.close()
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
    exchange: str = Query(default="bingx"),
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
    
    cache_key = f"{exchange.lower()}:{user_id}"
    now = time.time()
    cached = _symbols_cache.get(cache_key)
    
    symbols = []
    
    if cached and (now - cached["ts"]) < _SYMBOLS_TTL_SECONDS:
        symbols = cached["data"]
        logger.info(f"Using cached symbols for {exchange} ({len(symbols)} symbols)")
    else:
        # Obtener cuenta del usuario
        result = await db.execute(
            select(ExchangeAccount)
            .where(ExchangeAccount.user_id == user_id, ExchangeAccount.is_active == True)
            .limit(1)
        )
        account = result.scalar_one_or_none()
        
        if account:
            try:
                # Intentar obtener del exchange
                exchange_client = create_exchange(account)
                logger.info(f"Loading markets for {account.exchange}")
                symbols = await exchange_client.get_markets()
                logger.info(f"Loaded {len(symbols)} markets")
                # Filtrar solo perpetuals de USDT
                symbols = [s for s in symbols if ':USDT' in s]
                symbols.sort()
                logger.info(f"Filtered to {len(symbols)} USDT perpetuals")
                _symbols_cache[cache_key] = {"data": symbols, "ts": now}
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
        for s in symbols  # Sin límite artificial
    ]
