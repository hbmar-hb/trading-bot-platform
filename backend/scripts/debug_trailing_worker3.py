#!/usr/bin/env python3
import sys, os, asyncio, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL_SYNC", "postgresql+psycopg2://admin:Capnegret240323@localhost:5433/tradingbot")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://admin:Capnegret240323@localhost:5433/tradingbot")

from decimal import Decimal
from sqlalchemy import select
from app.services.database import AsyncSessionLocal_task as AsyncSessionLocal
from app.models.position import Position
from app.models.bot_config import BotConfig
from app.core.risk_manager import calculate_dynamic_sl_price, should_move_trailing_sl


async def main():
    print("=" * 70)
    print("DEBUG: Dynamic SL calculation step by step")
    print("=" * 70)
    
    position_id = "261114c6-c048-446e-9ea4-23eab8f69e6f"
    current_price = Decimal("95000")
    
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Position, BotConfig)
            .join(BotConfig, Position.bot_id == BotConfig.id)
            .where(Position.id == position_id)
        )
        result = await db.execute(stmt)
        row = result.first()
        
        if not row:
            print(f"❌ Position {position_id} not found")
            return
        
        position, bot = row
        entry = position.entry_price
        side = position.side
        current_sl = position.current_sl_price or Decimal("0")
        extra = dict(position.extra_config or {})
        
        print(f"Entry: {entry}")
        print(f"Current price: {current_price}")
        print(f"Current SL: {current_sl}")
        print(f"Side: {side}")
        
        # Calculate profit and R-multiple
        if side == "long":
            profit_pct = (current_price - entry) / entry * Decimal("100")
        else:
            profit_pct = (entry - current_price) / entry * Decimal("100")
        
        initial_risk_pct = Decimal(str(extra.get("initial_risk_pct", 0)))
        if initial_risk_pct <= 0:
            sl_pct = Decimal(str(bot.initial_sl_percentage or 0))
            initial_risk_pct = (
                sl_pct / Decimal(str(bot.leverage))
                if bot.use_roi_percentage and bot.leverage and bot.leverage > 1
                else sl_pct
            )
        
        r_multiple = (profit_pct / initial_risk_pct) if initial_risk_pct > 0 else Decimal("0")
        
        print(f"\nProfit %: {profit_pct:.4f}")
        print(f"Initial risk %: {initial_risk_pct:.4f}")
        print(f"R-multiple: {r_multiple:.4f}")
        
        # Dynamic SL config
        dy_cfg = bot.dynamic_sl_config or {}
        print(f"\nDynamic SL config: {dy_cfg}")
        
        if not dy_cfg.get("enabled"):
            print("Dynamic SL is disabled")
            return
        
        max_steps = int(dy_cfg.get("max_steps", 0))
        step_r = Decimal(str(dy_cfg.get("step_r", dy_cfg.get("step_percent", 0.5))))
        
        print(f"Max steps: {max_steps}")
        print(f"Step R: {step_r}")
        
        # Structural SL
        _STRUCTURAL_MARGIN = Decimal("0.005")
        support_levels = extra.get("support_levels", [])
        structural_sl = None
        
        if support_levels:
            if side == "long":
                structural_candidates = [
                    Decimal(str(l["price"]))
                    for l in support_levels
                    if current_price > Decimal(str(l["price"])) * (Decimal("1") + _STRUCTURAL_MARGIN)
                ]
                if structural_candidates:
                    structural_sl = max(structural_candidates)
            else:
                structural_candidates = [
                    Decimal(str(l["price"]))
                    for l in support_levels
                    if current_price < Decimal(str(l["price"])) * (Decimal("1") - _STRUCTURAL_MARGIN)
                ]
                if structural_candidates:
                    structural_sl = min(structural_candidates)
        
        print(f"\nStructural SL: {structural_sl}")
        
        # Mechanical SL
        mechanical_sl = None
        if initial_risk_pct > 0:
            steps_earned = int(r_multiple / step_r) if (step_r > 0 and r_multiple > 0) else 0
            if max_steps > 0:
                steps_earned = min(steps_earned, max_steps)
            
            steps_applied = int(extra.get("dynamic_sl_steps", 0))
            print(f"Steps earned: {steps_earned}, Steps applied: {steps_applied}")
            
            if steps_earned > steps_applied:
                effective_step_pct = initial_risk_pct * step_r
                print(f"Effective step %: {effective_step_pct:.4f}")
                try:
                    mechanical_sl = calculate_dynamic_sl_price(
                        entry, side,
                        initial_risk_pct,
                        effective_step_pct,
                        steps_earned,
                        leverage=None,
                        use_roi=False,
                    )
                    print(f"Mechanical SL: {mechanical_sl}")
                except Exception as e:
                    print(f"Error calculating mechanical SL: {e}")
                    traceback.print_exc()
            else:
                print("No new steps earned")
        
        # Hybrid
        if structural_sl is not None and mechanical_sl is not None:
            if side == "long":
                dynamic_sl = max(structural_sl, mechanical_sl)
            else:
                dynamic_sl = min(structural_sl, mechanical_sl)
            chosen = "hybrid"
        elif structural_sl is not None:
            dynamic_sl = structural_sl
            chosen = "structural"
        elif mechanical_sl is not None:
            dynamic_sl = mechanical_sl
            chosen = "mechanical"
        else:
            dynamic_sl = None
            chosen = "none"
        
        print(f"\nDynamic SL: {dynamic_sl} (source: {chosen})")
        
        if dynamic_sl is not None:
            should_move = should_move_trailing_sl(current_sl, dynamic_sl, side)
            print(f"Should move: {should_move}")
            if should_move:
                min_move = current_price * Decimal("0.001")
                print(f"Min improvement: {min_move:.4f}")
                print(f"Actual improvement: {abs(dynamic_sl - current_sl):.4f}")
            else:
                print("SL would not move (not better than current)")
        else:
            print("No dynamic SL calculated")


if __name__ == "__main__":
    asyncio.run(main())
