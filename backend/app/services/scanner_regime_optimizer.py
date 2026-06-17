"""Scanner Regime Optimizer — generates adaptive confluence parameters via LLM.

Caches results per (symbol, timeframe, regime) with a 4-hour TTL
to avoid repeated LLM costs for the same market context.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.services.database import AsyncSessionLocal_task
from app.models.scanner_regime_config import ScannerRegimeConfig
from app.models.ai_signal import AISignal
from app.services.llm_client import generate_structured, LLMError


_CACHE_TTL_MINUTES = 240  # 4 hours

_PROMPT_PATH = Path(__file__).parent.parent.parent / "ai" / "prompts" / "scanner_regime_optimization.md"


class AdaptiveScannerParams(BaseModel):
    """JSON schema for LLM-generated adaptive scanner parameters."""
    pivot_len: int = Field(default=5, ge=3, le=10)
    atr_mult: float = Field(default=0.3, ge=0.1, le=0.8)
    atr_len: int = Field(default=14, ge=7, le=21)
    entry_mode: str = Field(default="ob_or_fvg")
    weight_structure_CHoCH: float = Field(default=20.0, gt=0)
    weight_structure_BOS: float = Field(default=12.0, gt=0)
    weight_trigger_OB: float = Field(default=15.0, gt=0)
    weight_trigger_FVG: float = Field(default=10.0, gt=0)
    weight_sweep: float = Field(default=18.0, gt=0)
    weight_fvg_context: float = Field(default=4.0, gt=0)
    weight_pd_array: float = Field(default=10.0, gt=0)
    min_score_threshold: int = Field(default=55, ge=30, le=80)
    required_alignment_fvg_count: int = Field(default=1, ge=0, le=4)
    rationale: str = Field(default="")


def _load_prompt_template() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    logger.warning("[ScannerRegimeOptimizer] Prompt template not found, using fallback")
    return "{{symbol}} {{timeframe}} {{regime}} {{regime_confidence}} {{adx}} {{atr_percentile}} {{rel_volume}} {{realized_vol}} {{performance_summary}}"


def _render_prompt(
    symbol: str,
    timeframe: str,
    regime: str,
    regime_confidence: float,
    adx: float,
    atr_percentile: float,
    rel_volume: float,
    realized_vol: float,
    performance_summary: str,
) -> str:
    template = _load_prompt_template()
    return template.replace("{{symbol}}", symbol.upper()).replace(
        "{{timeframe}}", timeframe
    ).replace("{{regime}}", regime).replace(
        "{{regime_confidence}}", f"{regime_confidence:.2f}"
    ).replace("{{adx}}", f"{adx:.1f}").replace(
        "{{atr_percentile}}", f"{atr_percentile:.1f}"
    ).replace("{{rel_volume}}", f"{rel_volume:.2f}").replace(
        "{{realized_vol}}", f"{realized_vol:.4f}"
    ).replace("{{performance_summary}}", performance_summary or "Sin datos históricos disponibles.")


async def _fetch_performance_summary(symbol: str, timeframe: str, regime: str) -> str:
    """Aggregate recent REAL signal outcomes for this symbol+timeframe+regime combo."""
    try:
        async with AsyncSessionLocal_task() as db:
            # Count signals with outcomes in last 30 days — REAL ONLY
            since = datetime.now(timezone.utc) - timedelta(days=30)

            from app.models.position import Position
            from app.models.bot_config import BotConfig
            from sqlalchemy.dialects.postgresql import UUID as PGUUID
            real_signal_ids = (
                select(func.cast(Position.extra_config["ai_signal_id"].astext, PGUUID))
                .join(BotConfig, Position.bot_id == BotConfig.id)
                .where(BotConfig.paper_balance_id.is_(None))
                .where(Position.extra_config["ai_signal_id"].isnot(None))
                .subquery()
            )

            stmt = select(
                func.count(AISignal.id),
                func.count(AISignal.id).filter(AISignal.outcome == "SUCCESS"),
                func.count(AISignal.id).filter(AISignal.outcome == "FAILURE"),
                func.avg(AISignal.pnl_pct).filter(AISignal.outcome.isnot(None)),
            ).where(
                AISignal.id.in_(real_signal_ids),
                AISignal.ticker == symbol,
                AISignal.timeframe == timeframe,
                AISignal.features["market_regime"].astext == regime,
                AISignal.created_at >= since,
            )
            result = await db.execute(stmt)
            total, wins, losses, avg_pnl = result.first()

            if not total:
                return "Sin señales históricas con outcome para este régimen en los últimos 30 días."

            win_rate = (wins / total * 100) if total else 0
            avg_pnl_str = f"{avg_pnl:.2f}%" if avg_pnl is not None else "N/A"
            return (
                f"Últimos 30 días: {total} señales, "
                f"{wins} wins ({win_rate:.1f}%), {losses} losses, "
                f"PnL promedio: {avg_pnl_str}."
            )
    except Exception as exc:
        logger.warning(f"[ScannerRegimeOptimizer] Performance summary failed: {exc}")
        return "Error al obtener resumen de performance."


async def _generate_via_llm(
    symbol: str,
    timeframe: str,
    regime: str,
    regime_confidence: float,
    adx: float,
    atr_percentile: float,
    rel_volume: float,
    realized_vol: float,
) -> tuple[AdaptiveScannerParams, dict[str, Any]]:
    """Call LLM to generate adaptive parameters."""
    performance = await _fetch_performance_summary(symbol, timeframe, regime)
    prompt = _render_prompt(
        symbol, timeframe, regime, regime_confidence,
        adx, atr_percentile, rel_volume, realized_vol, performance,
    )

    logger.info(f"[ScannerRegimeOptimizer] Calling LLM for {symbol}/{timeframe}/{regime}")
    parsed, response = generate_structured(prompt, AdaptiveScannerParams, max_tokens=800)

    meta = {
        "model_used": response.model_used,
        "latency_ms": response.latency_ms,
        "cost_usd": response.cost_usd,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
    }
    return parsed, meta


def get_adaptive_params_sync(
    symbol: str,
    timeframe: str,
    regime: str,
    regime_confidence: float = 0.0,
    adx: float = 0.0,
    atr_percentile: float = 50.0,
    rel_volume: float = 1.0,
    realized_vol: float = 0.0,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Synchronous wrapper for get_adaptive_params (safe for Celery workers)."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(get_adaptive_params(
        symbol, timeframe, regime, regime_confidence,
        adx, atr_percentile, rel_volume, realized_vol, force_refresh,
    ))


async def get_adaptive_params(
    symbol: str,
    timeframe: str,
    regime: str,
    regime_confidence: float = 0.0,
    adx: float = 0.0,
    atr_percentile: float = 50.0,
    rel_volume: float = 1.0,
    realized_vol: float = 0.0,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return adaptive scanner parameters for the given market context.

    Returns a dict that can be passed as **kwargs to analyze_confluence().
    """
    symbol = symbol.upper()
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(minutes=_CACHE_TTL_MINUTES)

    async with AsyncSessionLocal_task() as db:
        # 1. Check cache
        if not force_refresh:
            stmt = select(ScannerRegimeConfig).where(
                ScannerRegimeConfig.symbol == symbol,
                ScannerRegimeConfig.timeframe == timeframe,
                ScannerRegimeConfig.regime == regime,
            )
            result = await db.execute(stmt)
            cached = result.scalar_one_or_none()
            if cached and cached.updated_at >= stale_threshold:
                logger.debug(
                    f"[ScannerRegimeOptimizer] Cache hit {symbol}/{timeframe}/{regime}"
                )
                return dict(cached.params)

        # 2. Generate via LLM
        try:
            parsed, meta = await _generate_via_llm(
                symbol, timeframe, regime, regime_confidence,
                adx, atr_percentile, rel_volume, realized_vol,
            )
        except LLMError as exc:
            logger.warning(f"[ScannerRegimeOptimizer] LLM failed: {exc}")
            # Fallback to empty dict (confluence_engine will use defaults)
            return {}

        params = parsed.model_dump(exclude={"rationale"})
        params["_rationale"] = parsed.rationale
        params["_generated_at"] = now.isoformat()

        # 3. Upsert to DB
        values = {
            "symbol": symbol,
            "timeframe": timeframe,
            "regime": regime,
            "params": params,
            "model_used": meta.get("model_used"),
            "latency_ms": meta.get("latency_ms"),
            "cost_usd": meta.get("cost_usd"),
            "updated_at": now,
        }
        upsert_stmt = (
            pg_insert(ScannerRegimeConfig)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["symbol", "timeframe", "regime"],
                set_={
                    "params": values["params"],
                    "model_used": values["model_used"],
                    "latency_ms": values["latency_ms"],
                    "cost_usd": values["cost_usd"],
                    "updated_at": values["updated_at"],
                },
            )
        )
        await db.execute(upsert_stmt)
        await db.commit()

        logger.info(
            f"[ScannerRegimeOptimizer] Generated config for {symbol}/{timeframe}/{regime} "
            f"cost={meta.get('cost_usd')} latency={meta.get('latency_ms')}ms"
        )
        return params
