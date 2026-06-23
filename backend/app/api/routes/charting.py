"""Chart endpoints - Smart Money Engine integration."""
import ccxt.async_support as ccxt
from loguru import logger
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import time
import json
from typing import Optional

from app.api.dependencies import get_current_user_id, require_developer_role
from app.exchanges.factory import create_exchange
from app.services.database import get_db
from app.services.cache import async_redis
from app.models.exchange_account import ExchangeAccount
from app.services.ict_engine import (
    SmartMoneyEngine,
    Candle,
    IndicatorConfig,
    StructureConfig,
    OBConfig,
    FVGConfig,
    IFVGConfig,
    FibConfig,
    VolumeConfig,
    MultiTimeframeConfig,
)
from app.services.ict_strategy import generate_ict_signal, StrategyConfig, scan_historical_signals

router = APIRouter(prefix="/charting", tags=["charting"], dependencies=[Depends(require_developer_role)])

# In-memory cache for symbol lists (TTL 5 min)
_symbols_cache = {}
_SYMBOLS_TTL_SECONDS = 300

# Candle cache TTL per timeframe (seconds)
_CANDLE_CACHE_TTL = {
    '1m': 30, '5m': 60, '10m': 90, '15m': 120, '30m': 180,
    '1h': 300, '2h': 600, '4h': 900, '1d': 3600, '1w': 7200, '1M': 14400,
}


def _resolve_htf(tf_name: str) -> str:
    mapping = {
        "1m": "5m", "5m": "15m", "15m": "1h",
        "1h": "4h", "4h": "1d", "1d": "1w",
        "1D": "1w", "1w": "1w", "1W": "1w",
    }
    return mapping.get(tf_name, "4h")


def _to_ccxt_symbol(symbol: str) -> str:
    """Convierte formatos nativos de exchange a CCXT."""
    if not symbol:
        return symbol
    if "/" in symbol:
        return symbol
    s = symbol.replace(".P", "").replace(".p", "")
    for quote in ["USDT", "USDC", "BTC", "ETH", "USD"]:
        if s.endswith(quote):
            base = s[: -len(quote)]
            return f"{base}/{quote}:{quote}"
    return symbol


_TIMEFRAME_MAP = {
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
    'M': '1M', '1M': '1M',
}


def _tf_to_seconds(tf: str) -> int:
    m = {'m': 60, 'h': 3600, 'd': 86400, 'w': 604800, 'M': 2592000}
    import re
    g = re.match(r"(\d+)([mhdwM])", tf)
    if not g:
        return 3600
    return int(g.group(1)) * m[g.group(2)]


async def _fetch_binance_pages(binance_client, sym, tf, since_ms, to_ts, max_calls=100):
    all_candles = []
    current_since = since_ms
    for _ in range(max_calls):
        try:
            ohlcv = await binance_client.fetch_ohlcv(sym, tf, since=current_since, limit=1000)
        except Exception as e:
            logger.warning(f"Binance fetch error: {e}")
            break
        if not ohlcv:
            break
        batch = [{"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in ohlcv]
        all_candles.extend(batch)
        current_since = (batch[-1]["time"] + 1) * 1000
        if batch[-1]["time"] >= to_ts:
            break
    return all_candles


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
    symbol    = _to_ccxt_symbol(symbol)
    timeframe = _TIMEFRAME_MAP.get(resolution, '1h')

    cache_key = f"chart:{symbol}:{timeframe}:{from_time}:{to_time}"
    try:
        cached = await async_redis.get(cache_key)
        if cached:
            logger.debug(f"[CHART CACHE HIT] {cache_key}")
            return json.loads(cached)
    except Exception:
        pass

    binance = ccxt.binance({'options': {'defaultType': 'swap'}})

    try:
        all_candles = await _fetch_binance_pages(binance, symbol, timeframe, from_time * 1000, to_time)

        if not all_candles:
            result = await db.execute(
                select(ExchangeAccount)
                .where(ExchangeAccount.user_id == user_id, ExchangeAccount.is_active == True)
                .limit(1)
            )
            account = result.scalar_one_or_none()
            if account:
                exchange = create_exchange(account)
                try:
                    candles = await exchange.get_candles(symbol, timeframe, limit=1000, since=from_time * 1000)
                    all_candles = candles or []
                finally:
                    await exchange.close()
            else:
                await binance.close()
                return {"s": "no_data", "errmsg": f"Symbol {symbol} not available"}

        await binance.close()

        if not all_candles:
            return {"s": "no_data", "errmsg": "No data available"}

        filtered = [c for c in all_candles if from_time <= c["time"] <= to_time] or all_candles

        result_data = {
            "s": "ok",
            "t": [c["time"]   for c in filtered],
            "o": [c["open"]   for c in filtered],
            "h": [c["high"]   for c in filtered],
            "l": [c["low"]    for c in filtered],
            "c": [c["close"]  for c in filtered],
            "v": [c["volume"] for c in filtered],
        }

        ttl = _CANDLE_CACHE_TTL.get(timeframe, 120)
        try:
            await async_redis.setex(cache_key, ttl, json.dumps(result_data))
        except Exception:
            pass

        return result_data

    except Exception as e:
        await binance.close()
        return {"s": "error", "errmsg": str(e)}


def _build_engine_config(
    timeframe: str,
    structure_swing_len: int = 10,
    structure_internal_len: int = 5,
    structure_min_atr_mult: float = 0.5,
    fvg_max_per_tf: int = 10,
    fvg_max_ifvg_per_tf: int = 5,
    fvg_min_size_atr_mult: float = 0.5,
    fvg_extension_bars: int = 5,
    ob_max_per_tf: int = 10,
    ob_lookback: int = 30,
    ob_extension_bars: int = 10,
    ob_mitigation: str = "wick",
    ob_min_volume_grade: float = 1.2,
    fib_enabled: bool = True,
    fib_show_ote: bool = True,
    show_ifvg: bool = True,
    show_strong_weak: bool = True,
    enable_htf: bool = True,
    htf_resolution: Optional[str] = None,
    htf_ema_len: int = 50,
) -> IndicatorConfig:
    htf_tf = htf_resolution or _resolve_htf(timeframe)
    return IndicatorConfig(
        structure=StructureConfig(
            timeframes=[timeframe],
            swing_len=structure_swing_len,
            internal_len=structure_internal_len,
            min_move_atr_mult=structure_min_atr_mult,
            show_strong_weak=show_strong_weak,
        ),
        ob=OBConfig(
            timeframes=[timeframe],
            max_per_tf=ob_max_per_tf,
            lookback=ob_lookback,
            extension_bars=ob_extension_bars,
            mitigation=ob_mitigation,
            min_volume_grade=ob_min_volume_grade,
        ),
        fvg=FVGConfig(
            timeframes=[timeframe],
            max_per_tf=fvg_max_per_tf,
            max_ifvg_per_tf=fvg_max_ifvg_per_tf,
            min_size_atr_mult=fvg_min_size_atr_mult,
            extension_bars=fvg_extension_bars,
        ),
        ifvg=IFVGConfig(timeframes=[timeframe] if show_ifvg else []),
        fib=FibConfig(enabled=fib_enabled, show_fib=fib_enabled, show_fib_ote=fib_show_ote),
        multi_tf=MultiTimeframeConfig(
            enabled=enable_htf,
            auto_htf=htf_resolution is None,
            htf_resolution=htf_tf,
            htf_ema_len=htf_ema_len,
        ),
    )


@router.get("/ict")
async def get_ict_indicators(
    symbol: str,
    resolution: str,
    from_time: int,
    to_time: int,
    structure_swing_len: int = Query(10, ge=3, le=50),
    structure_internal_len: int = Query(5, ge=2, le=20),
    structure_min_atr_mult: float = Query(0.5, ge=0.0, le=5.0),
    fvg_max_per_tf: int = Query(10, ge=1, le=50),
    fvg_max_ifvg_per_tf: int = Query(5, ge=0, le=20),
    fvg_min_size_atr_mult: float = Query(0.5, ge=0.0, le=5.0),
    fvg_extension_bars: int = Query(5, ge=0, le=100),
    ob_max_per_tf: int = Query(10, ge=1, le=50),
    ob_lookback: int = Query(30, ge=5, le=200),
    ob_extension_bars: int = Query(10, ge=0, le=100),
    ob_mitigation: str = Query("wick"),
    ob_min_volume_grade: float = Query(1.2, ge=1.0, le=3.0),
    fib_enabled: bool = Query(True),
    fib_show_ote: bool = Query(True),
    show_ifvg: bool = Query(True),
    show_strong_weak: bool = Query(True),
    enable_htf: bool = Query(True),
    htf_resolution: str = Query(None),
    htf_ema_len: int = Query(50, ge=10, le=200),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Smart Money Engine analysis: BOS/CHoCH, OBs, FVGs/IFVGs, Fibonacci, strong/weak levels, HTF EMA."""
    symbol    = _to_ccxt_symbol(symbol)
    timeframe = _TIMEFRAME_MAP.get(resolution, '1h')
    htf_tf    = htf_resolution or _resolve_htf(timeframe)

    cache_key = (
        f"ict:{symbol}:{timeframe}:{from_time}:{to_time}:"
        f"{structure_swing_len}:{structure_internal_len}:{structure_min_atr_mult}:"
        f"{fvg_max_per_tf}:{fvg_max_ifvg_per_tf}:{fvg_min_size_atr_mult}:{fvg_extension_bars}:"
        f"{ob_max_per_tf}:{ob_lookback}:{ob_extension_bars}:{ob_mitigation}:{ob_min_volume_grade}:"
        f"{int(fib_enabled)}:{int(fib_show_ote)}:{int(show_ifvg)}:{int(show_strong_weak)}:"
        f"{int(enable_htf)}:{htf_tf}:{htf_ema_len}:sme_v1"
    )
    try:
        cached = await async_redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    binance = ccxt.binance({'options': {'defaultType': 'swap'}})
    try:
        raw_candles = await _fetch_binance_pages(binance, symbol, timeframe, from_time * 1000, to_time)
        empty = {"boxes": [], "lines": [], "labels": [], "signal": None, "dashboard": None, "htf_bias": None, "timeframe": timeframe, "timestamp": 0}
        if not raw_candles:
            return empty

        candles = [Candle(open=c["open"], high=c["high"], low=c["low"], close=c["close"], volume=c["volume"], time=c["time"] * 1000) for c in raw_candles]
        current_price = candles[-1].close

        config = _build_engine_config(
            timeframe=timeframe,
            structure_swing_len=structure_swing_len,
            structure_internal_len=structure_internal_len,
            structure_min_atr_mult=structure_min_atr_mult,
            fvg_max_per_tf=fvg_max_per_tf,
            fvg_max_ifvg_per_tf=fvg_max_ifvg_per_tf,
            fvg_min_size_atr_mult=fvg_min_size_atr_mult,
            fvg_extension_bars=fvg_extension_bars,
            ob_max_per_tf=ob_max_per_tf,
            ob_lookback=ob_lookback,
            ob_extension_bars=ob_extension_bars,
            ob_mitigation=ob_mitigation,
            ob_min_volume_grade=ob_min_volume_grade,
            fib_enabled=fib_enabled,
            fib_show_ote=fib_show_ote,
            show_ifvg=show_ifvg,
            show_strong_weak=show_strong_weak,
            enable_htf=enable_htf,
            htf_resolution=htf_resolution,
            htf_ema_len=htf_ema_len,
        )

        candles_by_tf = {timeframe: candles}
        if enable_htf and htf_tf and htf_tf != timeframe:
            try:
                raw_htf = await _fetch_binance_pages(binance, symbol, htf_tf, from_time * 1000, to_time)
                if raw_htf:
                    htf_candles = [Candle(open=c["open"], high=c["high"], low=c["low"], close=c["close"], volume=c["volume"], time=c["time"] * 1000) for c in raw_htf]
                    candles_by_tf[htf_tf] = htf_candles
            except Exception as e:
                logger.warning(f"HTF fetch failed for {htf_tf}: {e}")

        output = SmartMoneyEngine(config).process(candles_by_tf, current_price, timeframe=timeframe)
        result_data = output.to_dict()

        ttl = _CANDLE_CACHE_TTL.get(timeframe, 120) * 2
        try:
            await async_redis.setex(cache_key, ttl, json.dumps(result_data))
        except Exception:
            pass

        return result_data
    finally:
        await binance.close()


@router.get("/ict/signal")
async def get_ict_signal(
    symbol: str,
    resolution: str,
    from_time: int,
    to_time: int,
    min_score: int = Query(4, ge=1, le=12),
    require_sweep: bool = Query(False),
    reject_asia: bool = Query(False),
    reject_equilibrium: bool = Query(False),
    min_rr: float = Query(1.2, ge=0.5, le=20.0),
    use_structural_sl_tp: bool = Query(True),
    structure_swing_len: int = Query(10, ge=3, le=50),
    structure_internal_len: int = Query(5, ge=2, le=20),
    structure_min_atr_mult: float = Query(0.5, ge=0.0, le=5.0),
    fvg_max_per_tf: int = Query(10, ge=1, le=50),
    fvg_max_ifvg_per_tf: int = Query(5, ge=0, le=20),
    fvg_min_size_atr_mult: float = Query(0.5, ge=0.0, le=5.0),
    fvg_extension_bars: int = Query(5, ge=0, le=100),
    ob_max_per_tf: int = Query(10, ge=1, le=50),
    ob_lookback: int = Query(30, ge=5, le=200),
    ob_extension_bars: int = Query(10, ge=0, le=100),
    ob_mitigation: str = Query("wick"),
    ob_min_volume_grade: float = Query(1.2, ge=1.0, le=3.0),
    fib_enabled: bool = Query(True),
    fib_show_ote: bool = Query(True),
    show_ifvg: bool = Query(True),
    show_strong_weak: bool = Query(True),
    require_premium_discount: bool = Query(False),
    enable_htf: bool = Query(True),
    htf_resolution: str = Query(None),
    htf_ema_len: int = Query(50, ge=10, le=200),
    require_htf_alignment: bool = Query(False),
    poi_proximity_pct: float = Query(0.5, ge=0.0, le=5.0),
    use_volume: bool = Query(True),
    vol_spike_threshold: float = Query(1.5, ge=1.0, le=5.0),
    recent_structure_bars: int = Query(30, ge=1, le=100),
    sl_tp_recency_bars: int = Query(20, ge=1, le=200),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Smart Money Engine trade signal for the given symbol + timeframe."""
    symbol    = _to_ccxt_symbol(symbol)
    timeframe = _TIMEFRAME_MAP.get(resolution, '1h')
    htf_tf    = htf_resolution or _resolve_htf(timeframe)

    binance = ccxt.binance({'options': {'defaultType': 'swap'}})
    try:
        raw_candles = await _fetch_binance_pages(binance, symbol, timeframe, from_time * 1000, to_time)
        if not raw_candles:
            return {"direction": "none", "strength": "none"}

        candles = [Candle(open=c["open"], high=c["high"], low=c["low"], close=c["close"], volume=c["volume"], time=c["time"] * 1000) for c in raw_candles]
        current_price = candles[-1].close

        config = _build_engine_config(
            timeframe=timeframe,
            structure_swing_len=structure_swing_len,
            structure_internal_len=structure_internal_len,
            structure_min_atr_mult=structure_min_atr_mult,
            fvg_max_per_tf=fvg_max_per_tf,
            fvg_max_ifvg_per_tf=fvg_max_ifvg_per_tf,
            fvg_min_size_atr_mult=fvg_min_size_atr_mult,
            fvg_extension_bars=fvg_extension_bars,
            ob_max_per_tf=ob_max_per_tf,
            ob_lookback=ob_lookback,
            ob_extension_bars=ob_extension_bars,
            ob_mitigation=ob_mitigation,
            ob_min_volume_grade=ob_min_volume_grade,
            fib_enabled=fib_enabled,
            fib_show_ote=fib_show_ote,
            show_ifvg=show_ifvg,
            show_strong_weak=show_strong_weak,
            enable_htf=enable_htf,
            htf_resolution=htf_resolution,
            htf_ema_len=htf_ema_len,
        )
        strategy_config = StrategyConfig(
            min_score=min_score,
            require_sweep=require_sweep,
            reject_asia=reject_asia,
            reject_equilibrium=reject_equilibrium,
            min_rr=min_rr,
            use_structural_sl_tp=use_structural_sl_tp,
            require_premium_discount=require_premium_discount,
            require_htf_alignment=require_htf_alignment,
            poi_proximity_pct=poi_proximity_pct,
            use_volume=use_volume,
            vol_spike_threshold=vol_spike_threshold,
            recent_structure_bars=recent_structure_bars,
            sl_tp_recency_bars=sl_tp_recency_bars,
        )

        candles_by_tf = {timeframe: candles}
        if enable_htf and htf_tf and htf_tf != timeframe:
            try:
                raw_htf = await _fetch_binance_pages(binance, symbol, htf_tf, from_time * 1000, to_time)
                if raw_htf:
                    htf_candles = [Candle(open=c["open"], high=c["high"], low=c["low"], close=c["close"], volume=c["volume"], time=c["time"] * 1000) for c in raw_htf]
                    candles_by_tf[htf_tf] = htf_candles
            except Exception as e:
                logger.warning(f"HTF fetch failed for {htf_tf}: {e}")

        output = SmartMoneyEngine(config).process(candles_by_tf, current_price, timeframe=timeframe)
        signal = generate_ict_signal(output, current_price, strategy_config, candles=candles)
        if signal.direction != 'none':
            signal.entry_time = candles[-1].time
        return signal.to_dict()
    finally:
        await binance.close()


@router.get("/ict/signals-history")
async def get_ict_signals_history(
    symbol: str,
    resolution: str,
    from_time: int,
    to_time: int,
    min_score: int = Query(4, ge=1, le=12),
    require_sweep: bool = Query(False),
    reject_asia: bool = Query(False),
    reject_equilibrium: bool = Query(False),
    min_rr: float = Query(1.2, ge=0.5, le=20.0),
    use_structural_sl_tp: bool = Query(True),
    structure_swing_len: int = Query(10, ge=3, le=50),
    structure_internal_len: int = Query(5, ge=2, le=20),
    structure_min_atr_mult: float = Query(0.5, ge=0.0, le=5.0),
    fvg_max_per_tf: int = Query(10, ge=1, le=50),
    fvg_max_ifvg_per_tf: int = Query(5, ge=0, le=20),
    fvg_min_size_atr_mult: float = Query(0.5, ge=0.0, le=5.0),
    fvg_extension_bars: int = Query(5, ge=0, le=100),
    ob_max_per_tf: int = Query(10, ge=1, le=50),
    ob_lookback: int = Query(30, ge=5, le=200),
    ob_extension_bars: int = Query(10, ge=0, le=100),
    ob_mitigation: str = Query("wick"),
    ob_min_volume_grade: float = Query(1.2, ge=1.0, le=3.0),
    fib_enabled: bool = Query(True),
    fib_show_ote: bool = Query(True),
    show_ifvg: bool = Query(True),
    show_strong_weak: bool = Query(True),
    require_premium_discount: bool = Query(False),
    enable_htf: bool = Query(True),
    htf_resolution: str = Query(None),
    htf_ema_len: int = Query(50, ge=10, le=200),
    require_htf_alignment: bool = Query(False),
    poi_proximity_pct: float = Query(0.5, ge=0.0, le=5.0),
    use_volume: bool = Query(True),
    vol_spike_threshold: float = Query(1.5, ge=1.0, le=5.0),
    recent_structure_bars: int = Query(30, ge=1, le=100),
    sl_tp_recency_bars: int = Query(20, ge=1, le=200),
    step: int = Query(3, ge=1, le=50),
    cooldown_bars: int = Query(5, ge=0, le=200),
    max_signals: int = Query(100, ge=1, le=200),
    max_forward_bars: int = Query(150, ge=10, le=500),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Scan historical candles for Smart Money Engine signals and evaluate each outcome."""
    symbol    = _to_ccxt_symbol(symbol)
    timeframe = _TIMEFRAME_MAP.get(resolution, '1h')
    htf_tf    = htf_resolution or _resolve_htf(timeframe)
    empty     = {"signals": [], "stats": {"total": 0, "wins": 0, "losses": 0, "open": 0, "win_rate": 0, "tp2_or_better": 0, "tp3_or_better": 0}}

    cache_key = (
        f"ict_hist:{symbol}:{timeframe}:{from_time}:{to_time}:"
        f"{min_score}:{int(require_sweep)}:{int(reject_asia)}:{int(reject_equilibrium)}:{min_rr}:"
        f"{structure_swing_len}:{structure_internal_len}:{structure_min_atr_mult}:"
        f"{fvg_max_per_tf}:{fvg_max_ifvg_per_tf}:{fvg_min_size_atr_mult}:{fvg_extension_bars}:"
        f"{ob_max_per_tf}:{ob_lookback}:{ob_extension_bars}:{ob_mitigation}:{ob_min_volume_grade}:"
        f"{int(fib_enabled)}:{int(show_ifvg)}:{int(show_strong_weak)}:"
        f"{int(require_premium_discount)}:{int(enable_htf)}:{htf_tf}:{htf_ema_len}:"
        f"{int(require_htf_alignment)}:{poi_proximity_pct}:{int(use_volume)}:{vol_spike_threshold}:"
        f"{step}:{cooldown_bars}:{max_signals}:{max_forward_bars}:sme_v1"
    )
    try:
        cached = await async_redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    binance = ccxt.binance({'options': {'defaultType': 'swap'}})
    try:
        raw_candles = await _fetch_binance_pages(binance, symbol, timeframe, from_time * 1000, to_time)
        if not raw_candles:
            return empty

        candles = [Candle(open=c["open"], high=c["high"], low=c["low"], close=c["close"], volume=c["volume"], time=c["time"] * 1000) for c in raw_candles]

        strategy_config = StrategyConfig(
            min_score=min_score,
            require_sweep=require_sweep,
            reject_asia=reject_asia,
            reject_equilibrium=reject_equilibrium,
            min_rr=min_rr,
            use_structural_sl_tp=use_structural_sl_tp,
            require_premium_discount=require_premium_discount,
            require_htf_alignment=require_htf_alignment,
            poi_proximity_pct=poi_proximity_pct,
            use_volume=use_volume,
            vol_spike_threshold=vol_spike_threshold,
            recent_structure_bars=recent_structure_bars,
            sl_tp_recency_bars=sl_tp_recency_bars,
        )

        engine_config = _build_engine_config(
            timeframe=timeframe,
            structure_swing_len=structure_swing_len,
            structure_internal_len=structure_internal_len,
            structure_min_atr_mult=structure_min_atr_mult,
            fvg_max_per_tf=fvg_max_per_tf,
            fvg_max_ifvg_per_tf=fvg_max_ifvg_per_tf,
            fvg_min_size_atr_mult=fvg_min_size_atr_mult,
            fvg_extension_bars=fvg_extension_bars,
            ob_max_per_tf=ob_max_per_tf,
            ob_lookback=ob_lookback,
            ob_extension_bars=ob_extension_bars,
            ob_mitigation=ob_mitigation,
            ob_min_volume_grade=ob_min_volume_grade,
            fib_enabled=fib_enabled,
            fib_show_ote=fib_show_ote,
            show_ifvg=show_ifvg,
            show_strong_weak=show_strong_weak,
            enable_htf=enable_htf,
            htf_resolution=htf_resolution,
            htf_ema_len=htf_ema_len,
        )

        result = scan_historical_signals(
            candles,
            timeframe=timeframe,
            strategy_config=strategy_config,
            engine_config=engine_config,
            step=step,
            cooldown_bars=cooldown_bars,
            max_signals=max_signals,
            max_forward_bars=max_forward_bars,
        )
    finally:
        await binance.close()

    ttl = _CANDLE_CACHE_TTL.get(timeframe, 120) * 4
    try:
        await async_redis.setex(cache_key, ttl, json.dumps(result))
    except Exception:
        pass

    return result


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
        result = await db.execute(
            select(ExchangeAccount)
            .where(ExchangeAccount.user_id == user_id, ExchangeAccount.is_active == True)
            .limit(1)
        )
        account = result.scalar_one_or_none()

        if account:
            try:
                exchange_client = create_exchange(account)
                logger.info(f"Loading markets for {account.exchange}")
                symbols = await exchange_client.get_markets()
                logger.info(f"Loaded {len(symbols)} markets")
                symbols = [s for s in symbols if ':USDT' in s]
                symbols.sort()
                logger.info(f"Filtered to {len(symbols)} USDT perpetuals")
                _symbols_cache[cache_key] = {"data": symbols, "ts": now}
            except Exception as e:
                logger.error(f"Error loading markets: {e}", exc_info=True)
                symbols = POPULAR_SYMBOLS
        else:
            logger.warning("No exchange account found, using default symbols")
            symbols = POPULAR_SYMBOLS[:20]

    if not symbols:
        logger.warning("No symbols loaded, using fallback")
        symbols = POPULAR_SYMBOLS

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
        for s in symbols
    ]
