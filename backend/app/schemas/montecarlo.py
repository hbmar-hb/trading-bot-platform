"""
Schemas Pydantic para el módulo Monte Carlo.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, List, Any

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# ESTRATEGIAS
# ═══════════════════════════════════════════════════════════════

class StrategyParameter(BaseModel):
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    type: str = "float"  # int | float | bool | str


class MonteCarloStrategyCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    code: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    indicators: List[str] = Field(default_factory=list)


class MonteCarloStrategyUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    code: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    indicators: Optional[List[str]] = None
    is_active: Optional[bool] = None


class MonteCarloStrategyResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: Optional[str]
    code: str
    parameters: dict
    indicators: list
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════════════
# BACKTEST
# ═══════════════════════════════════════════════════════════════

class BacktestRequest(BaseModel):
    symbol: str = Field(..., description="Ej: BTCUSDT")
    timeframe: str = Field(default="1h")
    from_date: datetime
    to_date: datetime
    initial_capital: float = Field(default=10000.0, gt=0)
    fee_rate: float = Field(default=0.0006, ge=0)
    slippage_pct: float = Field(default=0.0, ge=0)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class BacktestTradeResponse(BaseModel):
    entry_time: datetime
    exit_time: datetime
    direction: int
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_abs: float
    duration_bars: int
    max_drawdown_pct: float
    close_reason: str


class BacktestMetricsResponse(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: Optional[float]
    total_return_pct: float
    total_pnl_abs: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    cagr: float
    expectancy: float
    avg_trade_pct: float
    best_trade_pct: float
    worst_trade_pct: float
    avg_bars: float


class BacktestResponse(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    symbol: str
    timeframe: str
    from_date: datetime
    to_date: datetime
    initial_capital: float
    fee_rate: float
    slippage_pct: float
    trades: List[BacktestTradeResponse]
    metrics: BacktestMetricsResponse
    equity_curve: List[dict]
    status: str
    error_message: Optional[str]
    created_at: datetime


# ═══════════════════════════════════════════════════════════════
# SIMULACIÓN MONTE CARLO
# ═══════════════════════════════════════════════════════════════

class SimulationRequest(BaseModel):
    simulation_type: str = Field(..., pattern="^(return_shuffle|bootstrap|param_perturb|equity_path)$")
    n_simulations: int = Field(default=10000, ge=100, le=50000)
    thresholds: Optional[dict] = Field(default_factory=lambda: {
        "min_prob_profit": 0.70,
        "min_prob_sharpe": 0.60,
        "max_prob_ruin": 0.05,
        "min_sharpe_p5": 0.5,
    })
    save_equity_curves: bool = Field(default=False)


class SimulationPercentiles(BaseModel):
    p5: float
    p50: float
    p95: float


class SimulationProbabilities(BaseModel):
    profit: float
    sharpe_above_1: float
    dd_below_20pct: float
    ruin: float


class SimulationResultData(BaseModel):
    simulation_type: str
    n_simulations: int
    original_metrics: dict
    percentiles: dict
    probabilities: SimulationProbabilities


class SimulationValidation(BaseModel):
    passed: bool
    score: float
    checks: dict
    failures: List[str]
    timestamp: str


class SimulationResponse(BaseModel):
    id: uuid.UUID
    backtest_id: uuid.UUID
    simulation_type: str
    n_simulations: int
    result: SimulationResultData
    validation: SimulationValidation
    equity_curves: Optional[List[List[float]]]
    created_at: datetime


# ═══════════════════════════════════════════════════════════════
# VALIDACIÓN EN VIVO
# ═══════════════════════════════════════════════════════════════

class TradeInput(BaseModel):
    entry_time: datetime
    exit_time: datetime
    direction: int = Field(..., ge=-1, le=1)
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_abs: float = 0.0
    duration_bars: int = 0
    max_drawdown_pct: float = 0.0


class LiveValidationRequest(BaseModel):
    trades: List[TradeInput]
    initial_capital: float = Field(default=10000.0, gt=0)
    thresholds: Optional[dict] = Field(default_factory=lambda: {
        "min_prob_profit": 0.70,
        "min_prob_sharpe": 0.60,
        "max_prob_ruin": 0.05,
        "min_sharpe_p5": 0.5,
    })


class LiveValidationResponse(BaseModel):
    result: SimulationResultData
    validation: SimulationValidation
    recommendation: str
    should_trade: bool


# ═══════════════════════════════════════════════════════════════
# INDICADORES
# ═══════════════════════════════════════════════════════════════

class IndicatorInfo(BaseModel):
    name: str
    description: str


# ═══════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════

class StrategyTemplateResponse(BaseModel):
    name: str
    description: str
    code: str
    parameters: dict
    indicators: list


class SymbolListResponse(BaseModel):
    symbols: List[dict]


# ═══════════════════════════════════════════════════════════════
# IA ENGINE INTEGRATION
# ═══════════════════════════════════════════════════════════════

class AIEvaluationRequest(BaseModel):
    strategy_id: uuid.UUID
    symbol: str
    timeframe: str = "1h"
    lookback_days: int = Field(default=90, ge=30, le=180)
    recalibrate: bool = Field(default=False)
    save_results: bool = Field(default=False)


class AIScanRequest(BaseModel):
    strategy_id: uuid.UUID
    lookback_days: int = Field(default=90, ge=30, le=180)


class RecalibrationRequest(BaseModel):
    strategy_id: uuid.UUID
    symbol: str
    timeframe: str = "1h"
    lookback_days: int = Field(default=90, ge=30, le=180)
    target_score: float = Field(default=70.0, ge=0, le=100)


class RecalibrationResult(BaseModel):
    best_params: dict
    all_results: List[dict]
    metrics: dict
    equity_curve: List[dict]
    monte_carlo: Optional[dict]
    joint_score_after: Optional[float]
    recommendation_after: Optional[str]


class AIEvaluationResponse(BaseModel):
    symbol: str
    timeframe: str
    ai_signal: Optional[dict]
    ai_score: float
    backtest: Optional[dict]
    monte_carlo: Optional[dict]
    mc_score: float
    joint_score: float
    recommendation: str
    recalibration: Optional[RecalibrationResult]


class AIScanItem(BaseModel):
    symbol: str
    timeframe: str
    ai_score: float
    ai_signal: Optional[dict]
    latest_scan: Optional[dict]
    recommendation: str


class AIScanResponse(BaseModel):
    evaluations: List[AIScanItem]


# ═══════════════════════════════════════════════════════════════
# IA ENGINE BATCH EVALUATION
# ═══════════════════════════════════════════════════════════════

class EvalBatchItem(BaseModel):
    symbol: str
    timeframe: str = "1h"


class AIEvalBatchRequest(BaseModel):
    strategy_id: uuid.UUID
    evaluations: List[EvalBatchItem]
    lookback_days: int = Field(default=90, ge=30, le=180)
    recalibrate: bool = Field(default=False)


class AIEvalBatchResult(BaseModel):
    symbol: str
    timeframe: str
    ai_score: float
    mc_score: float
    joint_score: float
    recommendation: str
    ai_signal: Optional[dict] = None
    backtest: Optional[dict] = None
    monte_carlo: Optional[dict] = None
    passed: bool


class AIEvalBatchResponse(BaseModel):
    results: List[AIEvalBatchResult]


class ApplyEvalToBotRequest(BaseModel):
    bot_id: str  # UUID o nombre del bot (case-insensitive)
    symbol: str
    timeframe: str
    strategy_id: uuid.UUID
    leverage: Optional[int] = None
    position_value: Optional[float] = None
    setup_base: bool = True  # Habilitar como setup base de IA


class ApplyEvalToBotResponse(BaseModel):
    success: bool
    message: str
    bot_id: uuid.UUID
    strategy_id: uuid.UUID | None = None
    old_config: dict
    new_config: dict
