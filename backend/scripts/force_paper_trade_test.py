#!/usr/bin/env python3
"""
Force a high-score paper trade for BTC/USDT 1d to validate the full pipeline:
Signal → Activator → Position → Trailing Worker (structural SL).

Usage: cd backend && python scripts/force_paper_trade_test.py
"""
import sys, asyncio, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://admin:Capnegret240323@localhost:5433/tradingbot")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://admin:Capnegret240323@localhost:5433/tradingbot")

from datetime import datetime, timezone
from decimal import Decimal
from loguru import logger
import ccxt.async_support as ccxt

from app.services.ai_scanner import build_signal
from app.services.database import SessionLocal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.ai_scan import AILatestScan
from app.models.ai_signal import AISignal


async def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 200):
    exchange = ccxt.bingx({"options": {"defaultType": "swap"}})
    ccxt_sym = f"{symbol}/USDT:USDT"
    ohlcv = await exchange.fetch_ohlcv(ccxt_sym, timeframe, limit=limit)
    await exchange.close()
    return ohlcv


def save_signal(sig: AISignal) -> str:
    from app.services.ai_scanner import signal_to_dict
    
    with SessionLocal() as db:
        db.add(sig)
        db.commit()
        db.refresh(sig)
        
        # Upsert latest scan
        values = {
            "symbol": sig.ticker,
            "timeframe": sig.timeframe,
            "status": "SIGNAL",
            "context": {},
            "signal_data": signal_to_dict(sig),
            "signal_id": sig.id,
            "scanned_at": datetime.now(timezone.utc),
        }
        stmt = (
            pg_insert(AILatestScan)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["symbol", "timeframe"],
                set_={k: values[k] for k in ("status", "context", "signal_data", "signal_id", "scanned_at")},
            )
        )
        db.execute(stmt)
        db.commit()
        
        return str(sig.id)


def force_activate(signal_id: str):
    """Call the activator directly (bypass Celery to avoid Redis issues)."""
    from app.engines.bot_activator import activate
    result = activate(signal_id)
    return result


def main():
    print("=" * 70)
    print("FORCE PAPER TRADE TEST: BTC/USDT 1d")
    print("=" * 70)
    
    symbol = "BTCUSDT"
    timeframe = "1d"
    bot_id = "7927bd13-d350-4bd9-9892-210a0e8ff49a"  # BTCbot_1d_paper
    ccxt_symbol = "BTC/USDT:USDT"
    
    # 1. Fetch real data
    print(f"\n1. Fetching OHLCV for {symbol}/{timeframe}...")
    ohlcv = asyncio.run(fetch_ohlcv("BTC", "1d", limit=200))
    print(f"   Fetched {len(ohlcv)} candles")
    
    # 2. Build signal using real pipeline
    print(f"\n2. Building signal via real pipeline...")
    result_dict, sig = build_signal(symbol, timeframe, ohlcv)
    
    if sig is None:
        print(f"   ⚠️  No signal from pipeline. Creating synthetic signal from ICT analysis...")
        from app.core.ict_engine import analyze as ict_analyze
        from app.engines.confluence_engine import analyze_confluence
        
        closed = [{"open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in ohlcv[:-1]]
        confluence = analyze_confluence(closed, symbol, timeframe)
        
        if confluence is None:
            print("   ❌ Confluence also returned None. Aborting.")
            return
        
        # Build a synthetic AISignal
        from app.engines.signal_quality_engine import assess_quality
        quality = assess_quality(confluence)
        
        sig = AISignal(
            ticker=symbol,
            ccxt_symbol=ccxt_symbol,
            timeframe=timeframe,
            direction=confluence.direction,
            score=confluence.score,
            confidence=confluence.confidence,
            entry_price=confluence.entry_price,
            entry_zone_low=confluence.entry_zone[0],
            entry_zone_high=confluence.entry_zone[1],
            stop_loss=confluence.stop_loss,
            take_profit_1=confluence.take_profit_1,
            take_profit_2=confluence.take_profit_2,
            features=confluence.features,
            components=confluence.components,
            warnings=confluence.warnings,
            explanation=confluence.explanation,
            quality_score=quality.quality_score,
            quality_tier=quality.quality_tier,
            anti_fake_status=quality.anti_fake_status,
            success_probability=0.85,
            red_flags=quality.red_flags,
            green_flags=quality.green_flags,
            signal_time=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
    
    # 3. Override score to ensure activation
    original_score = sig.score
    sig.score = 80.0  # Force high score to pass all filters
    sig.quality_tier = "STRONG"
    sig.anti_fake_status = "CLEAR"
    sig.success_probability = 0.92
    print(f"   Original score: {original_score:.1f} → Forced to: {sig.score:.1f}")
    print(f"   Direction: {sig.direction}")
    print(f"   Entry: {sig.entry_price}")
    print(f"   SL: {sig.stop_loss}")
    print(f"   TP1: {sig.take_profit_1}")
    
    features = sig.features or {}
    fwd = features.get("forward_levels", [])
    sup = features.get("support_levels", [])
    print(f"   Forward levels: {len(fwd)}")
    print(f"   Support levels: {len(sup)}")
    
    # 4. Save to DB
    print(f"\n3. Saving signal to DB...")
    signal_id = save_signal(sig)
    print(f"   ✅ Signal ID: {signal_id}")
    
    # 5. Trigger activator
    print(f"\n4. Triggering bot activator for bot {bot_id}...")
    result = force_activate(signal_id)
    print(f"   Task sent: {result.id}")
    
    # 6. Wait and check position
    print(f"\n5. Waiting 10s for activator to process...")
    import time
    time.sleep(10)
    
    print(f"\n6. Checking created position...")
    with SessionLocal() as db:
        from sqlalchemy import select
        from app.models.position import Position
        
        stmt = (
            select(Position)
            .where(Position.extra_config["ai_signal_id"].astext == signal_id)
            .order_by(Position.opened_at.desc())
        )
        pos = db.execute(stmt).scalars().first()
        
        if pos is None:
            print("   ❌ No position found for this signal")
            print("   (Activator may have rejected it — check worker logs)")
            return
        
        print(f"   ✅ Position found!")
        print(f"      ID: {pos.id}")
        print(f"      Symbol: {pos.symbol}")
        print(f"      Side: {pos.side}")
        print(f"      Entry: {pos.entry_price}")
        print(f"      SL: {pos.current_sl_price}")
        print(f"      Status: {pos.status}")
        
        extra = pos.extra_config or {}
        has_support = extra.get("support_levels") is not None and len(extra.get("support_levels", [])) > 0
        has_forward = extra.get("forward_levels") is not None and len(extra.get("forward_levels", [])) > 0
        
        print(f"\n      extra_config structural data:")
        print(f"      - support_levels: {'✅' if has_support else '❌'} ({len(extra.get('support_levels', []))} items)")
        print(f"      - forward_levels: {'✅' if has_forward else '❌'} ({len(extra.get('forward_levels', []))} items)")
        print(f"      - tp1_source: {extra.get('tp1_source', 'N/A')}")
        print(f"      - adjusted_trailing_config: {'✅' if extra.get('adjusted_trailing_config') else '❌'}")
        print(f"      - adjusted_breakeven_config: {'✅' if extra.get('adjusted_breakeven_config') else '❌'}")
        
        # 7. Simulate trailing worker evaluation
        print(f"\n7. Simulating trailing worker at current price...")
        current_price = float(sig.entry_price) * 1.02  # Simulate 2% profit
        
        from app.core.risk_manager import calculate_dynamic_sl_price
        
        side = pos.side
        entry = Decimal(str(pos.entry_price))
        initial_sl = Decimal(str(pos.current_sl_price))
        
        # Structural SL
        _STRUCTURAL_MARGIN = Decimal("0.005")
        support_levels = extra.get("support_levels", [])
        structural_sl = None
        
        if support_levels:
            if side == "long":
                candidates = [
                    Decimal(str(l["price"]))
                    for l in support_levels
                    if Decimal(str(current_price)) > Decimal(str(l["price"])) * (Decimal("1") + _STRUCTURAL_MARGIN)
                ]
                if candidates:
                    structural_sl = max(candidates)
            else:
                candidates = [
                    Decimal(str(l["price"]))
                    for l in support_levels
                    if Decimal(str(current_price)) < Decimal(str(l["price"])) * (Decimal("1") - _STRUCTURAL_MARGIN)
                ]
                if candidates:
                    structural_sl = min(candidates)
        
        print(f"      Current price (simulated): {current_price:.2f}")
        print(f"      Initial SL: {float(initial_sl):.2f}")
        print(f"      Structural SL: {float(structural_sl):.2f}" if structural_sl else "      Structural SL: N/A (no levels activated)")
        
        if structural_sl:
            improvement = abs(float(structural_sl - initial_sl) / float(initial_sl) * 100)
            print(f"      SL improvement: {improvement:.2f}%")
    
    print(f"\n{'='*70}")
    print("✅ FORCE PAPER TRADE TEST COMPLETED")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
