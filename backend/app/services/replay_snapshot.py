"""
Trade Replay Snapshot — captura estado completo de un trade para reproducibilidad.

Se ejecuta inmediatamente después de abrir posición.
Guarda: features, predictions, weights, regime, config, execution, gates, OHLCV.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models.position import Position
    from app.models.ai_signal import AISignal
    from app.models.bot_config import BotConfig

from app.models.trade_replay_snapshot import TradeReplaySnapshot

# ── Constants ──────────────────────────────────────────────
OHLCV_CONTEXT_BARS = 20


def _safe_decimal(val) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _model_version_from_registry() -> tuple[str | None, str | None]:
    """Detect current model version and artifact path from registry."""
    try:
        from ai.registry import MODEL_PATH
        meta_path = MODEL_PATH.parent / "retrain_meta.json"
        if meta_path.exists():
            import json
            with open(meta_path) as f:
                meta = json.load(f)
            version = meta.get("model_version") or meta.get("artifact", "unknown")
            return version, str(MODEL_PATH)
    except Exception:
        pass
    return None, None


def _fetch_ohlcv_context(exchange, symbol: str, timeframe: str = "1h", limit: int = OHLCV_CONTEXT_BARS) -> list[dict]:
    """Fetch last N OHLCV bars for context."""
    try:
        if hasattr(exchange, "_client") and hasattr(exchange._client, "fetch_ohlcv"):
            import asyncio
            ohlcv = asyncio.get_event_loop().run_until_complete(
                exchange._client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            )
            if ohlcv:
                return [
                    {
                        "timestamp": c[0],
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    }
                    for c in ohlcv
                ]
    except Exception:
        pass
    return []


def capture_replay_snapshot(
    db: Session,
    position: Position,
    sig: AISignal,
    bot: BotConfig,
    fill_price: Decimal,
    quantity: Decimal,
    effective_leverage: int,
    slippage_estimate: dict | None,
    sor_strategy: str | None,
    dynamic_horizon_meta: dict | None,
    kelly_meta: dict | None,
    gates: dict | None,
    exchange=None,
) -> TradeReplaySnapshot | None:
    """
    Captures a full replay snapshot after position open.
    Returns the snapshot record or None on failure.
    """
    try:
        model_version, model_path = _model_version_from_registry()

        # Build execution snapshot
        execution = {
            "fill_price": float(fill_price) if fill_price else None,
            "quantity": float(quantity) if quantity else None,
            "leverage": effective_leverage,
            "entry_price_signal": float(sig.entry_price) if sig.entry_price else None,
            "stop_loss_signal": float(sig.stop_loss) if sig.stop_loss else None,
            "tp1_signal": float(sig.take_profit_1) if sig.take_profit_1 else None,
            "tp2_signal": float(sig.take_profit_2) if sig.take_profit_2 else None,
            "sor_strategy": sor_strategy,
            "slippage_estimate": slippage_estimate,
            "dynamic_horizon": dynamic_horizon_meta,
            "kelly": kelly_meta,
        }

        # Bot config snapshot (relevant fields only)
        bot_config_snapshot = {
            "ai_signal_mode": bot.ai_signal_mode,
            "ai_signal_config": bot.ai_signal_config,
            "position_sizing_type": bot.position_sizing_type,
            "position_value": float(bot.position_value) if bot.position_value else None,
            "leverage": bot.leverage,
            "is_paper_trading": bot.is_paper_trading,
        }

        # Gates snapshot
        gates_snapshot = gates or {}

        # OHLCV context
        ohlcv_context = []
        if exchange:
            ohlcv_context = _fetch_ohlcv_context(exchange, bot.symbol, timeframe=sig.timeframe or "1h")

        # Funding and spread at exec
        funding_rate = None
        spread = None
        atr_value = None
        try:
            if sig.features:
                atr_value = _safe_decimal(sig.features.get("atr_value"))
                spread = _safe_decimal(sig.features.get("spread_atr"))
        except Exception:
            pass

        snapshot = TradeReplaySnapshot(
            id=uuid.uuid4(),
            position_id=position.id,
            ai_signal_id=sig.id,
            bot_id=bot.id,
            features=sig.features or {},
            success_probability=_safe_decimal(sig.success_probability),
            calibrated_confidence=_safe_decimal(sig.calibrated_confidence),
            quality_tier=sig.quality_tier,
            anti_fake_status=sig.anti_fake_status,
            score=_safe_decimal(sig.score),
            quality_score=_safe_decimal(sig.quality_score),
            confluence_weights=sig.components or {},
            regime=sig.features.get("market_regime") if sig.features else None,
            regime_confidence=_safe_decimal(sig.features.get("regime_confidence")) if sig.features else None,
            htf_bias=sig.features.get("htf_bias") if sig.features else None,
            bot_config_snapshot=bot_config_snapshot,
            execution=execution,
            gates_snapshot=gates_snapshot,
            ohlcv_context=ohlcv_context,
            funding_rate_at_exec=funding_rate,
            spread_at_exec=spread,
            atr_value_at_exec=atr_value,
            model_version=model_version,
            model_artifact_path=model_path,
            symbol=bot.symbol,
            direction=sig.direction,
            timeframe=sig.timeframe,
            executed_at=datetime.now(timezone.utc),
        )
        db.add(snapshot)
        db.commit()
        return snapshot
    except Exception as exc:
        from loguru import logger
        logger.warning(f"[ReplaySnapshot] Failed to capture snapshot: {exc}")
        db.rollback()
        return None
