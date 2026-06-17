#!/usr/bin/env python3
"""
Pipeline test across multiple tickers/timeframes.
Finds the first setup that produces forward_levels + support_levels.

Usage: cd backend && python scripts/test_multi_ticker_pipeline.py
"""
import sys, asyncio, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://admin:Capnegret240323@localhost:5433/tradingbot")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://admin:Capnegret240323@localhost:5433/tradingbot")

from app.core.ict_engine import analyze as ict_analyze
from app.engines.confluence_engine import analyze_confluence
import ccxt.async_support as ccxt


async def fetch_candles(ticker: str, timeframe: str, limit: int = 200):
    client = ccxt.bingx({"options": {"defaultType": "swap"}})
    symbol = f"{ticker}/USDT:USDT"
    try:
        ohlcv = await client.fetch_ohlcv(symbol, timeframe, limit=limit)
    except Exception as e:
        await client.close()
        raise e
    await client.close()
    return [
        {"time": int(c[0] / 1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]}
        for c in ohlcv
    ]


def test_ticker(ticker: str, timeframe: str):
    print(f"\n{'='*60}")
    print(f"Testing {ticker}/{timeframe}")
    print(f"{'='*60}")
    
    try:
        candles = asyncio.run(fetch_candles(ticker, timeframe, limit=200))
    except Exception as e:
        print(f"Fetch error: {e}")
        return False
    
    print(f"Fetched {len(candles)} candles, latest close={candles[-1]['close']}")
    
    ict = ict_analyze(candles, pivot_len=5, atr_mult=0.3, atr_len=14, entry_mode="ob_or_fvg")
    print(f"ICT: signal={ict.signal}, bias={ict.bias}, grade={ict.grade}")
    print(f"     forward_levels={len(ict.forward_levels)}, support_levels={len(ict.support_levels)}")
    
    confluence = analyze_confluence(candles, ticker, timeframe)
    if confluence:
        print(f"Confluence: dir={confluence.direction}, score={confluence.score}")
        print(f"            TP1={confluence.take_profit_1} (src={confluence.features.get('tp1_source')})")
        print(f"            TP2={confluence.take_profit_2} (src={confluence.features.get('tp2_source')})")
        print(f"            fwd_in_features={len(confluence.features.get('forward_levels',[]))}")
        print(f"            sup_in_features={len(confluence.features.get('support_levels',[]))}")
        
        has_fwd = len(ict.forward_levels) > 0
        has_sup = len(ict.support_levels) > 0
        has_signal = ict.signal != "none"
        
        if has_signal and has_fwd and has_sup:
            print("\n✅✅✅ VALID SETUP FOUND ✅✅✅")
            return True
    else:
        print("Confluence: None")
    
    return False


def main():
    tickers = ["BTC", "ETH", "SOL", "PEPE", "FARTCOIN", "WIF", "BONK", "DOGE"]
    timeframes = ["1d", "4h", "1h"]
    
    for tf in timeframes:
        for ticker in tickers:
            if test_ticker(ticker, tf):
                print("\nStopping after first valid setup.")
                return
    
    print("\nNo valid setup found across tested tickers/timeframes.")


if __name__ == "__main__":
    main()
