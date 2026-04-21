"""Chart endpoints - Using same logic as markets-by-exchange"""
import ccxt.async_support as ccxt
from fastapi import APIRouter, Depends, Query, HTTPException, status
import uuid
import time

from app.api.dependencies import get_current_user_id

router = APIRouter(prefix="/charting", tags=["charting"])

# In-memory cache for symbol lists (TTL 5 min)
_symbols_cache = {}
_SYMBOLS_TTL_SECONDS = 300


@router.get("/symbols")
async def search_symbols(
    query: str = Query(default=""),
    exchange: str = Query(default="bingx"),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Get symbols - EXACT same logic as /exchange-accounts/markets-by-exchange/{exchange}
    Returns list of symbols like ["BTC/USDT:USDT", "ETH/USDT:USDT", ...]
    """
    cache_key = exchange.lower()
    now = time.time()
    cached = _symbols_cache.get(cache_key)

    try:
        if cached and (now - cached["ts"]) < _SYMBOLS_TTL_SECONDS:
            symbols = cached["data"]
        else:
            # Same code as working endpoint
            exchange_class = getattr(ccxt, exchange.lower(), None)
            if not exchange_class:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Exchange no soportado: {exchange}"
                )

            ex = exchange_class({'enableRateLimit': True})
            markets = await ex.load_markets()

            # Filter perpetuals (same logic)
            perpetuals = [
                symbol for symbol, market in markets.items()
                if market.get('swap') and market.get('linear')
            ]

            await ex.close()

            symbols = sorted(perpetuals)
            _symbols_cache[cache_key] = {"data": symbols, "ts": now}

        # Filter by query if provided
        if query:
            q = query.upper()
            symbols = [s for s in symbols if q in s.upper()]

        # Return format expected by frontend (sin límite artificial)
        return [
            {"symbol": s, "description": s.replace("/USDT:USDT", "").replace("/USDC:USDC", "")}
            for s in symbols
        ]

    except HTTPException:
        raise
    except Exception as e:
        # Fallback
        return [
            {"symbol": "BTC/USDT:USDT", "description": "BTC"},
            {"symbol": "ETH/USDT:USDT", "description": "ETH"},
            {"symbol": "SOL/USDT:USDT", "description": "SOL"},
            {"symbol": "XRP/USDT:USDT", "description": "XRP"},
        ]


@router.get("/history")
async def get_history(
    symbol: str,
    resolution: str,
    from_time: int,
    to_time: int,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Get candle data using CCXT directly."""
    try:
        ex = ccxt.bingx({'enableRateLimit': True})
        
        # Map resolution to timeframe
        tf_map = {
            '1': '1m', '1m': '1m',
            '5': '5m', '5m': '5m', 
            '15': '15m', '15m': '15m',
            '30': '30m', '30m': '30m',
            '60': '1h', '1h': '1h',
            '240': '4h', '4h': '4h',
            'D': '1d', '1d': '1d', '1D': '1d'
        }
        timeframe = tf_map.get(resolution, '1h')
        
        # Fetch OHLCV
        since = from_time * 1000  # CCXT uses milliseconds
        ohlcv = await ex.fetch_ohlcv(symbol, timeframe, since=since, limit=500)
        await ex.close()
        
        if not ohlcv or len(ohlcv) == 0:
            return {"s": "no_data", "errmsg": "No data available"}
        
        # TradingView UDF format
        return {
            "s": "ok",
            "t": [int(x[0]/1000) for x in ohlcv],
            "o": [x[1] for x in ohlcv],
            "h": [x[2] for x in ohlcv],
            "l": [x[3] for x in ohlcv],
            "c": [x[4] for x in ohlcv],
            "v": [x[5] for x in ohlcv],
        }
        
    except Exception as e:
        return {"s": "error", "errmsg": str(e)}
