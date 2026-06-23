"""
API Routes para el módulo Monte Carlo + Backtesting de Estrategias.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np
from loguru import logger

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_developer_role
from app.models.montecarlo import MonteCarloStrategy, MonteCarloBacktest, MonteCarloSimulation
from app.models.bot_config import BotConfig
from app.schemas.montecarlo import (
    MonteCarloStrategyCreate,
    MonteCarloStrategyUpdate,
    MonteCarloStrategyResponse,
    BacktestRequest,
    BacktestResponse,
    BacktestTradeResponse,
    BacktestMetricsResponse,
    SimulationRequest,
    SimulationResponse,
    SimulationResultData,
    SimulationProbabilities,
    SimulationValidation,
    LiveValidationRequest,
    LiveValidationResponse,
    IndicatorInfo,
    StrategyTemplateResponse,
    SymbolListResponse,
    AIEvaluationRequest,
    AIEvaluationResponse,
    AIScanRequest,
    AIScanResponse,
    AIScanItem,
    RecalibrationRequest,
    RecalibrationResult,
    AIEvalBatchRequest,
    AIEvalBatchResponse,
    AIEvalBatchResult,
    ApplyEvalToBotRequest,
    ApplyEvalToBotResponse,
)
from app.engines.montecarlo_engine import MonteCarloEngine, TradingValidator
from app.engines.montecarlo_backtest_engine import (
    fetch_ohlcv,
    execute_strategy_code,
    run_backtest,
    run_backtest_with_walk_forward,
    get_default_strategy,
    _to_ccxt_symbol,
)
from app.engines.montecarlo_indicators import list_indicators
from app.services.database import get_db

router = APIRouter(prefix="/montecarlo", tags=["montecarlo"])


# ═══════════════════════════════════════════════════════════════
# HELPERS: serialización JSON-safe (numpy → tipos nativos)
# ═══════════════════════════════════════════════════════════════

def _clean_json_values(obj):
    """Convierte recursivamente np.int64, np.float64, np.ndarray → tipos Python nativos."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _clean_json_values(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_json_values(v) for v in obj]
    return obj


# ═══════════════════════════════════════════════════════════════
# ESTRATEGIAS CRUD
# ═══════════════════════════════════════════════════════════════

@router.get("/strategies", response_model=List[MonteCarloStrategyResponse])
async def list_strategies(
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonteCarloStrategy)
        .where(MonteCarloStrategy.user_id == user.id)
        .order_by(desc(MonteCarloStrategy.created_at))
    )
    return result.scalars().all()


@router.post("/strategies", response_model=MonteCarloStrategyResponse)
async def create_strategy(
    data: MonteCarloStrategyCreate,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    strategy = MonteCarloStrategy(
        user_id=user.id,
        name=data.name,
        description=data.description,
        code=data.code,
        parameters=data.parameters,
        indicators=data.indicators,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.get("/strategies/{strategy_id}", response_model=MonteCarloStrategyResponse)
async def get_strategy(
    strategy_id: uuid.UUID,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonteCarloStrategy)
        .where(MonteCarloStrategy.id == strategy_id, MonteCarloStrategy.user_id == user.id)
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(404, "Estrategia no encontrada")
    return strategy


@router.put("/strategies/{strategy_id}", response_model=MonteCarloStrategyResponse)
async def update_strategy(
    strategy_id: uuid.UUID,
    data: MonteCarloStrategyUpdate,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonteCarloStrategy)
        .where(MonteCarloStrategy.id == strategy_id, MonteCarloStrategy.user_id == user.id)
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(404, "Estrategia no encontrada")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(strategy, field, value)

    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.delete("/strategies/{strategy_id}")
async def delete_strategy(
    strategy_id: uuid.UUID,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonteCarloStrategy)
        .where(MonteCarloStrategy.id == strategy_id, MonteCarloStrategy.user_id == user.id)
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(404, "Estrategia no encontrada")

    await db.delete(strategy)
    await db.commit()
    return {"status": "deleted"}


# ═══════════════════════════════════════════════════════════════
# BACKTEST
# ═══════════════════════════════════════════════════════════════

@router.post("/strategies/{strategy_id}/backtest", response_model=BacktestResponse)
async def run_strategy_backtest(
    strategy_id: uuid.UUID,
    req: BacktestRequest,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonteCarloStrategy)
        .where(MonteCarloStrategy.id == strategy_id, MonteCarloStrategy.user_id == user.id)
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(404, "Estrategia no encontrada")

    # Ejecutar backtest
    backtest_record = MonteCarloBacktest(
        strategy_id=strategy.id,
        user_id=user.id,
        symbol=req.symbol.upper(),
        timeframe=req.timeframe,
        from_date=req.from_date,
        to_date=req.to_date,
        initial_capital=req.initial_capital,
        fee_rate=req.fee_rate,
        slippage_pct=req.slippage_pct,
        status="running",
    )
    db.add(backtest_record)
    await db.commit()
    await db.refresh(backtest_record)

    try:
        # 1. Obtener datos
        df = await fetch_ohlcv(req.symbol, req.timeframe, req.from_date, req.to_date)

        # 2. Ejecutar estrategia
        params = {**strategy.parameters, **req.parameters}
        signals = execute_strategy_code(strategy.code, df, params)

        # 3. Simular backtest con Walk-Forward Validation (FASE 3C)
        wfv_result = run_backtest_with_walk_forward(
            df, signals,
            initial_capital=req.initial_capital,
            fee_rate=req.fee_rate,
            slippage_pct=req.slippage_pct,
            oos_split=0.2,
        )
        result_bt = wfv_result.train_result

        # 4. Guardar resultados
        trades_json = [
            {
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_pct": t.pnl_pct,
                "pnl_abs": t.pnl_abs,
                "duration_bars": t.duration_bars,
                "max_drawdown_pct": t.max_drawdown_pct,
                "close_reason": t.close_reason,
            }
            for t in result_bt.trades
        ]

        metrics_json = {
            "total_trades": result_bt.metrics.total_trades,
            "winning_trades": result_bt.metrics.winning_trades,
            "losing_trades": result_bt.metrics.losing_trades,
            "win_rate": result_bt.metrics.win_rate,
            "profit_factor": result_bt.metrics.profit_factor,
            "total_return_pct": result_bt.metrics.total_return_pct,
            "total_pnl_abs": result_bt.metrics.total_pnl_abs,
            "sharpe_ratio": result_bt.metrics.sharpe_ratio,
            "sortino_ratio": result_bt.metrics.sortino_ratio,
            "max_drawdown_pct": result_bt.metrics.max_drawdown_pct,
            "cagr": result_bt.metrics.cagr,
            "expectancy": result_bt.metrics.expectancy,
            "avg_trade_pct": result_bt.metrics.avg_trade_pct,
            "best_trade_pct": result_bt.metrics.best_trade_pct,
            "worst_trade_pct": result_bt.metrics.worst_trade_pct,
            "avg_bars": result_bt.metrics.avg_bars,
            # FASE 3C: Walk-forward validation results
            "oos": {
                "total_trades": wfv_result.oos_result.metrics.total_trades,
                "win_rate": wfv_result.oos_result.metrics.win_rate,
                "profit_factor": wfv_result.oos_result.metrics.profit_factor,
                "sharpe_ratio": wfv_result.oos_result.metrics.sharpe_ratio,
                "max_drawdown_pct": wfv_result.oos_result.metrics.max_drawdown_pct,
                "overfit_detected": wfv_result.overfit_detected,
                "overfit_reasons": wfv_result.overfit_reasons,
            },
        }

        backtest_record.trades = _clean_json_values(trades_json)
        backtest_record.metrics = _clean_json_values(metrics_json)
        backtest_record.equity_curve = _clean_json_values(result_bt.equity_curve)
        backtest_record.status = "completed"

        await db.commit()
        await db.refresh(backtest_record)

        return _backtest_to_response(backtest_record)

    except Exception as e:
        import traceback
        backtest_record.status = "failed"
        backtest_record.error_message = str(e)
        await db.commit()
        traceback_str = traceback.format_exc()
        print(f"[BACKTEST ERROR] strategy_id={strategy_id}, symbol={req.symbol}, error={e}\n{traceback_str}")
        # Extraer línea del código del usuario de la traza
        user_line = ""
        for line in traceback_str.splitlines():
            if 'File "<string>"' in line:
                user_line = line.strip()
        detail = f"Error en tu código de estrategia: {e}"
        if user_line:
            detail += f"\nTraza: {user_line}"
        raise HTTPException(400, detail)


@router.get("/backtests", response_model=List[BacktestResponse])
async def list_backtests(
    strategy_id: Optional[uuid.UUID] = Query(None),
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    q = select(MonteCarloBacktest).where(MonteCarloBacktest.user_id == user.id)
    if strategy_id:
        q = q.where(MonteCarloBacktest.strategy_id == strategy_id)
    q = q.order_by(desc(MonteCarloBacktest.created_at))
    result = await db.execute(q)
    return [_backtest_to_response(b) for b in result.scalars().all()]


# ═══════════════════════════════════════════════════════════════
# SIMULACIÓN MONTE CARLO
# ═══════════════════════════════════════════════════════════════

@router.post("/backtests/{backtest_id}/simulate", response_model=SimulationResponse)
async def run_simulation(
    backtest_id: uuid.UUID,
    req: SimulationRequest,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonteCarloBacktest)
        .where(MonteCarloBacktest.id == backtest_id, MonteCarloBacktest.user_id == user.id)
    )
    backtest = result.scalar_one_or_none()
    if not backtest:
        raise HTTPException(404, "Backtest no encontrado")

    if not backtest.trades:
        raise HTTPException(400, "El backtest no tiene trades para simular")

    # Ejecutar simulación
    engine = MonteCarloEngine(initial_capital=float(backtest.initial_capital))
    engine.load_from_dicts(backtest.trades)

    sim_type = req.simulation_type
    n_sims = req.n_simulations
    thresholds = req.thresholds or {}

    if sim_type == "return_shuffle":
        mc_result = engine.run_return_shuffle(n_sims, save_equity_curves=req.save_equity_curves)
    elif sim_type == "bootstrap":
        mc_result = engine.run_bootstrap(n_sims)
    elif sim_type == "equity_path":
        mc_result = engine.run_equity_path(n_sims)
    elif sim_type == "param_perturb":
        raise HTTPException(400, "Parameter perturbation requiere implementación adicional")
    else:
        raise HTTPException(400, f"Tipo de simulación no soportado: {sim_type}")

    validation = engine.validate_strategy(mc_result, **thresholds)

    # Guardar en DB
    equity_curves_data = None
    if mc_result.equity_curves is not None:
        equity_curves_data = mc_result.equity_curves.tolist()

    sim_record = MonteCarloSimulation(
        backtest_id=backtest.id,
        user_id=user.id,
        simulation_type=sim_type,
        n_simulations=n_sims,
        result=mc_result.to_dict(),
        equity_curves=equity_curves_data,
        validation=validation,
    )
    db.add(sim_record)
    await db.commit()
    await db.refresh(sim_record)

    return _simulation_to_response(sim_record)


@router.get("/simulations", response_model=List[SimulationResponse])
async def list_simulations(
    backtest_id: Optional[uuid.UUID] = Query(None),
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    q = select(MonteCarloSimulation).where(MonteCarloSimulation.user_id == user.id)
    if backtest_id:
        q = q.where(MonteCarloSimulation.backtest_id == backtest_id)
    q = q.order_by(desc(MonteCarloSimulation.created_at))
    result = await db.execute(q)
    return [_simulation_to_response(s) for s in result.scalars().all()]


# ═══════════════════════════════════════════════════════════════
# VALIDACIÓN EN VIVO
# ═══════════════════════════════════════════════════════════════

@router.post("/validate-live", response_model=LiveValidationResponse)
async def validate_live(
    req: LiveValidationRequest,
    user = Depends(require_developer_role),
):
    validator = TradingValidator(initial_capital=req.initial_capital)

    trades = [
        {
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl_pct": t.pnl_pct,
            "pnl_abs": t.pnl_abs,
            "duration_bars": t.duration_bars,
            "max_drawdown_pct": t.max_drawdown_pct,
        }
        for t in req.trades
    ]

    result = validator.validate_live_from_dicts(trades)
    thresholds = req.thresholds or {}
    should_trade = validator.should_trade(min_score=thresholds.get("min_score", 70.0))

    return LiveValidationResponse(
        result=SimulationResultData(**result["result"]),
        validation=SimulationValidation(**result["validation"]),
        recommendation=result["recommendation"],
        should_trade=should_trade,
    )


# ═══════════════════════════════════════════════════════════════
# IA ENGINE INTEGRATION
# ═══════════════════════════════════════════════════════════════

@router.post("/ai-engine/eval", response_model=AIEvaluationResponse)
async def ai_engine_eval(
    req: AIEvaluationRequest,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Evalúa un símbolo+timeframe con el motor de IA y la estrategia Monte Carlo.
    Retorna señal IA, backtest, simulación Monte Carlo y joint score.
    """
    from app.services.ai_monte_carlo_service import evaluate_symbol_strategy

    result = await evaluate_symbol_strategy(
        symbol=req.symbol.upper(),
        timeframe=req.timeframe,
        strategy_id=req.strategy_id,
        user_id=user.id,
        db=db,
        lookback_days=req.lookback_days,
        recalibrate=req.recalibrate,
    )

    if "error" in result:
        raise HTTPException(400, result["error"])

    result = _clean_json_values(result)

    return AIEvaluationResponse(
        symbol=result["symbol"],
        timeframe=result["timeframe"],
        ai_signal=result.get("ai_signal"),
        ai_score=result["ai_score"],
        backtest=result.get("backtest"),
        monte_carlo=result.get("monte_carlo"),
        mc_score=result["mc_score"],
        joint_score=result["joint_score"],
        recommendation=result["recommendation"],
        recalibration=RecalibrationResult(**result["recalibration"]) if result.get("recalibration") else None,
    )


@router.post("/ai-engine/scan", response_model=AIScanResponse)
async def ai_engine_scan(
    req: AIScanRequest,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Escanea el watchlist del usuario y evalúa cada par con IA.
    """
    from app.services.ai_monte_carlo_service import scan_watchlist

    evaluations = await scan_watchlist(
        strategy_id=req.strategy_id,
        user_id=user.id,
        db=db,
        lookback_days=req.lookback_days,
    )

    return AIScanResponse(
        evaluations=[AIScanItem(**e) for e in evaluations]
    )


@router.post("/ai-engine/recalibrate", response_model=RecalibrationResult)
async def ai_engine_recalibrate(
    req: RecalibrationRequest,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Fuerza recalibración de parámetros de estrategia para un par+timeframe.
    """
    from app.services.ai_monte_carlo_service import recalibrate_strategy
    from app.models.montecarlo import MonteCarloStrategy

    result = await db.execute(
        select(MonteCarloStrategy)
        .where(MonteCarloStrategy.id == req.strategy_id, MonteCarloStrategy.user_id == user.id)
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(404, "Estrategia no encontrada")

    rec = await recalibrate_strategy(
        symbol=req.symbol.upper(),
        timeframe=req.timeframe,
        strategy=strategy,
        lookback_days=req.lookback_days,
        target_score=req.target_score,
    )

    if not rec:
        raise HTTPException(400, "No se pudo recalibrar la estrategia")

    return RecalibrationResult(
        best_params=rec["best_params"],
        all_results=rec["all_results"],
        metrics=rec["metrics"],
        equity_curve=rec["equity_curve"],
        monte_carlo=rec.get("monte_carlo"),
        joint_score_after=rec.get("joint_score_after"),
        recommendation_after=rec.get("recommendation_after"),
    )


# ═══════════════════════════════════════════════════════════════
# IA ENGINE BATCH EVALUATION
# ═══════════════════════════════════════════════════════════════

@router.post("/ai-engine/eval-batch", response_model=AIEvalBatchResponse)
async def ai_engine_eval_batch(
    req: AIEvalBatchRequest,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Evalúa múltiples pares/timeframes con IA + Backtest + Monte Carlo.
    Retorna resultados comparativos para todos los pares seleccionados.
    """
    from app.services.ai_monte_carlo_service import evaluate_symbol_strategy

    results = []
    for item in req.evaluations:
        try:
            result = await evaluate_symbol_strategy(
                symbol=item.symbol.upper(),
                timeframe=item.timeframe,
                strategy_id=req.strategy_id,
                user_id=user.id,
                db=db,
                lookback_days=req.lookback_days,
                recalibrate=req.recalibrate,
            )

            # Limpiar valores numpy antes de serializar
            result = _clean_json_values(result)

            if "error" in result:
                results.append(AIEvalBatchResult(
                    symbol=item.symbol,
                    timeframe=item.timeframe,
                    ai_score=0,
                    mc_score=0,
                    joint_score=0,
                    recommendation="ERROR",
                    passed=False,
                ))
                continue

            results.append(AIEvalBatchResult(
                symbol=result["symbol"],
                timeframe=result["timeframe"],
                ai_score=result.get("ai_score", 0),
                mc_score=result.get("mc_score", 0),
                joint_score=result.get("joint_score", 0),
                recommendation=result.get("recommendation", "NO_OPERAR"),
                ai_signal=result.get("ai_signal"),
                backtest=result.get("backtest"),
                monte_carlo=result.get("monte_carlo"),
                passed=result.get("joint_score", 0) >= 60,
            ))
        except Exception as exc:
            logger.error(f"[EVAL-BATCH] Error evaluando {item.symbol}/{item.timeframe}: {exc}")
            results.append(AIEvalBatchResult(
                symbol=item.symbol,
                timeframe=item.timeframe,
                ai_score=0,
                mc_score=0,
                joint_score=0,
                recommendation="ERROR",
                passed=False,
            ))

    return AIEvalBatchResponse(results=results)


# ═══════════════════════════════════════════════════════════════
# INDICADORES Y UTILIDADES
# ═══════════════════════════════════════════════════════════════

@router.get("/indicators", response_model=List[IndicatorInfo])
async def get_indicators(
    _user = Depends(require_developer_role),
):
    return [IndicatorInfo(**i) for i in list_indicators()]


@router.get("/strategy-template", response_model=StrategyTemplateResponse)
async def get_strategy_template(
    _user = Depends(require_developer_role),
):
    tpl = get_default_strategy()
    return StrategyTemplateResponse(**tpl)


import time

# Caché simple para símbolos de Binance (TTL: 5 minutos)
_SYMBOLS_CACHE = {"data": None, "ts": 0}
_SYMBOLS_CACHE_TTL = 300


def _fetch_binance_symbols() -> list:
    """Obtiene pares USDT perpetual de Binance vía CCXT."""
    global _SYMBOLS_CACHE
    now = time.time()
    if _SYMBOLS_CACHE["data"] and (now - _SYMBOLS_CACHE["ts"]) < _SYMBOLS_CACHE_TTL:
        return _SYMBOLS_CACHE["data"]

    try:
        import ccxt
        exchange = ccxt.binanceusdm({
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
        markets = exchange.load_markets()
        symbols = []
        for symbol, market in markets.items():
            # Solo perpetual swap USDT activo
            if (
                market.get("type") == "swap"
                and market.get("linear", False)
                and market.get("quote") == "USDT"
                and market.get("settle") == "USDT"
                and market.get("active", False)
                and not market.get("expiry")
            ):
                symbols.append(symbol)

        symbols = sorted(set(symbols))
        _SYMBOLS_CACHE = {"data": symbols, "ts": now}
        return symbols
    except Exception as e:
        logger.warning(f"[SYMBOLS] Error fetching Binance markets: {e}")
        # Fallback a lista popular si CCXT falla
        return [
            "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT",
            "DOGE/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT", "LINK/USDT:USDT",
            "DOT/USDT:USDT", "LTC/USDT:USDT", "BCH/USDT:USDT", "UNI/USDT:USDT",
            "ATOM/USDT:USDT", "ETC/USDT:USDT", "XLM/USDT:USDT", "NEAR/USDT:USDT",
        ]


def _denormalize_symbol(symbol: str) -> str:
    """Convert normalized watchlist symbol (e.g. BTCUSDT) to CCXT format (BTC/USDT:USDT)."""
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}/USDT:USDT"
    elif symbol.endswith("USD"):
        return f"{symbol[:-3]}/USD:USD"
    return symbol


@router.get("/symbols", response_model=SymbolListResponse)
async def get_symbols(
    query: str = Query(default=""),
    source: str = Query(default="watchlist", description="'watchlist' for AI watchlist symbols, 'binance' for all Binance perpetuals"),
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    """Lista de símbolos para Monte Carlo. Defaults to user's AI watchlist."""
    from app.models.ai_scan import AIWatchlistItem

    if source == "binance":
        symbols_list = _fetch_binance_symbols()
    else:
        # Import AI watchlist symbols
        rows = await db.execute(
            select(AIWatchlistItem.symbol)
            .where(AIWatchlistItem.user_id == user.id)
            .order_by(AIWatchlistItem.symbol)
        )
        symbols_list = [_denormalize_symbol(r[0]) for r in rows.all()]

    if query:
        symbols_list = [s for s in symbols_list if query.upper() in s.upper()]

    symbols = [
        {
            "symbol": s,
            "description": s.replace("/USDT:USDT", "").replace("/USDT", ""),
            "type": "crypto",
        }
        for s in symbols_list
    ]
    return SymbolListResponse(symbols=symbols)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

@router.post("/bots/apply-eval", response_model=ApplyEvalToBotResponse)
async def apply_eval_to_bot(
    req: ApplyEvalToBotRequest,
    user = Depends(require_developer_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Aplica la configuración de una evaluación IA a un bot existente.
    Cambia timeframe, symbol, leverage y position_value según la evaluación.
    Acepta bot_id (UUID) o bot_name (nombre del bot, case-insensitive).
    """
    from sqlalchemy import func

    # Intentar buscar por UUID primero
    bot = None
    try:
        bot_uuid = uuid.UUID(req.bot_id)
        result = await db.execute(
            select(BotConfig)
            .where(BotConfig.id == bot_uuid, BotConfig.user_id == user.id)
        )
        bot = result.scalar_one_or_none()
    except ValueError:
        pass  # No es un UUID válido, buscar por nombre

    # Si no se encontró por UUID, buscar por nombre (case-insensitive)
    if not bot:
        result = await db.execute(
            select(BotConfig)
            .where(
                func.lower(BotConfig.bot_name) == req.bot_id.lower(),
                BotConfig.user_id == user.id,
            )
        )
        bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(404, f"Bot no encontrado: '{req.bot_id}'. Usa el UUID o el nombre exacto del bot.")

    old_config = {
        "symbol": bot.symbol,
        "timeframe": bot.timeframe,
        "leverage": bot.leverage,
        "position_value": float(bot.position_value),
        "strategy_id": str(bot.montecarlo_config.get("strategy_id")) if bot.montecarlo_config else None,
    }

    # Actualizar bot con la nueva configuración
    bot.symbol = req.symbol.upper()
    bot.timeframe = req.timeframe
    if req.leverage is not None:
        bot.leverage = req.leverage
    if req.position_value is not None:
        bot.position_value = req.position_value
    bot.updated_at = datetime.now(timezone.utc)

    # Guardar estrategia asociada en montecarlo_config
    mc_cfg = bot.montecarlo_config or {}
    if req.setup_base:
        mc_cfg["enabled"] = True
        mc_cfg["mode"] = "setup_base"
        mc_cfg["min_score"] = mc_cfg.get("min_score", 70.0)
        mc_cfg["n_trades_lookback"] = mc_cfg.get("n_trades_lookback", 50)

        # Inicializar optimized_params con los defaults de la estrategia
        from app.models.montecarlo import MonteCarloStrategy
        strategy = await db.get(MonteCarloStrategy, req.strategy_id)
        if strategy and strategy.parameters:
            default_params = {
                k: v.get("default", v.get("value", 0))
                for k, v in strategy.parameters.items()
            }
            mc_cfg["optimized_params"] = default_params

        # Ejecutar MCSetupEngine para generar el primer setup context
        try:
            from app.engines.mc_setup_engine import MCSetupEngine
            setup_context = await MCSetupEngine.run_async(
                strategy_id=req.strategy_id,
                symbol=req.symbol.upper(),
                timeframe=req.timeframe,
                params=mc_cfg.get("optimized_params"),
                lookback_days=90,
            )
            MCSetupEngine.set_cached(bot, setup_context)
            logger.info(
                f"[MC APPLY] Initial setup context generated for bot {bot.bot_name}: "
                f"bias={setup_context.direction_bias}, tier={setup_context.confidence_tier}"
            )
        except Exception as exc:
            logger.warning(f"[MC APPLY] Could not generate initial setup context: {exc}")
            # No fallamos la operación si el setup no se genera ahora; se recalculará luego
    else:
        # Solo guardar referencia, no habilitar como setup base
        mc_cfg["enabled"] = False
        mc_cfg.pop("mode", None)

    mc_cfg["strategy_id"] = str(req.strategy_id)
    mc_cfg["strategy_symbol"] = req.symbol.upper()
    mc_cfg["strategy_timeframe"] = req.timeframe
    mc_cfg["applied_at"] = datetime.now(timezone.utc).isoformat()
    bot.montecarlo_config = mc_cfg

    await db.commit()
    await db.refresh(bot)

    new_config = {
        "symbol": bot.symbol,
        "timeframe": bot.timeframe,
        "leverage": bot.leverage,
        "position_value": float(bot.position_value),
        "strategy_id": str(req.strategy_id),
    }

    return ApplyEvalToBotResponse(
        success=True,
        message=(
            f"Bot '{bot.bot_name}' actualizado:\n"
            f"• Par: {old_config['symbol']} → {new_config['symbol']}\n"
            f"• Timeframe: {old_config['timeframe']} → {new_config['timeframe']}\n"
            f"• Estrategia Monte Carlo: {str(req.strategy_id)[:8]}..."
        ),
        bot_id=bot.id,
        old_config=old_config,
        new_config=new_config,
    )


def _backtest_to_response(bt: MonteCarloBacktest) -> BacktestResponse:
    trades = [
        BacktestTradeResponse(
            entry_time=datetime.fromisoformat(t["entry_time"].replace("Z", "+00:00")) if isinstance(t["entry_time"], str) else t["entry_time"],
            exit_time=datetime.fromisoformat(t["exit_time"].replace("Z", "+00:00")) if isinstance(t["exit_time"], str) else t["exit_time"],
            direction=t["direction"],
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            pnl_pct=t["pnl_pct"],
            pnl_abs=t["pnl_abs"],
            duration_bars=t["duration_bars"],
            max_drawdown_pct=t["max_drawdown_pct"],
            close_reason=t.get("close_reason", ""),
        )
        for t in bt.trades
    ]

    m = bt.metrics
    metrics = BacktestMetricsResponse(
        total_trades=m.get("total_trades", 0),
        winning_trades=m.get("winning_trades", 0),
        losing_trades=m.get("losing_trades", 0),
        win_rate=m.get("win_rate", 0.0),
        profit_factor=m.get("profit_factor"),
        total_return_pct=m.get("total_return_pct", 0.0),
        total_pnl_abs=m.get("total_pnl_abs", 0.0),
        sharpe_ratio=m.get("sharpe_ratio", 0.0),
        sortino_ratio=m.get("sortino_ratio", 0.0),
        max_drawdown_pct=m.get("max_drawdown_pct", 0.0),
        cagr=m.get("cagr", 0.0),
        expectancy=m.get("expectancy", 0.0),
        avg_trade_pct=m.get("avg_trade_pct", 0.0),
        best_trade_pct=m.get("best_trade_pct", 0.0),
        worst_trade_pct=m.get("worst_trade_pct", 0.0),
        avg_bars=m.get("avg_bars", 0.0),
    )

    return BacktestResponse(
        id=bt.id,
        strategy_id=bt.strategy_id,
        symbol=bt.symbol,
        timeframe=bt.timeframe,
        from_date=bt.from_date,
        to_date=bt.to_date,
        initial_capital=float(bt.initial_capital),
        fee_rate=float(bt.fee_rate),
        slippage_pct=float(bt.slippage_pct),
        trades=trades,
        metrics=metrics,
        equity_curve=bt.equity_curve,
        status=bt.status,
        error_message=bt.error_message,
        created_at=bt.created_at,
    )


def _simulation_to_response(sim: MonteCarloSimulation) -> SimulationResponse:
    result = sim.result
    validation = sim.validation

    probs = result.get("probabilities", {})
    probabilities = SimulationProbabilities(
        profit=probs.get("profit", 0.0),
        sharpe_above_1=probs.get("sharpe_above_1", 0.0),
        dd_below_20pct=probs.get("dd_below_20pct", 0.0),
        ruin=probs.get("ruin", 0.0),
    )

    result_data = SimulationResultData(
        simulation_type=result.get("simulation_type", ""),
        n_simulations=result.get("n_simulations", 0),
        original_metrics=result.get("original_metrics", {}),
        percentiles=result.get("percentiles", {}),
        probabilities=probabilities,
    )

    validation_data = SimulationValidation(
        passed=validation.get("passed", False),
        score=validation.get("score", 0.0),
        checks=validation.get("checks", {}),
        failures=validation.get("failures", []),
        timestamp=validation.get("timestamp", ""),
    )

    return SimulationResponse(
        id=sim.id,
        backtest_id=sim.backtest_id,
        simulation_type=sim.simulation_type,
        n_simulations=sim.n_simulations,
        result=result_data,
        validation=validation_data,
        equity_curves=sim.equity_curves,
        created_at=sim.created_at,
    )
