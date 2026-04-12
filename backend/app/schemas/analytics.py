import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class TradeSummary(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float                 # 0.0 – 1.0
    profit_factor: Optional[float]  # ganancia_total / pérdida_total
    total_pnl: Decimal
    average_pnl: Decimal
    best_trade: Decimal
    worst_trade: Decimal
    max_drawdown: Decimal           # máxima caída desde un pico de equity acumulado
    avg_duration_hours: float       # duración media de trades (horas)
    current_streak: int             # + = racha de wins, - = racha de losses
    long_trades: int
    short_trades: int
    long_win_rate: float
    short_win_rate: float
    long_pnl: Decimal
    short_pnl: Decimal


class BotStats(BaseModel):
    bot_id: uuid.UUID
    bot_name: str
    symbol: str
    status: str
    total_trades: int
    winning_trades: int
    win_rate: float
    profit_factor: Optional[float]
    total_pnl: Decimal
    avg_pnl: Decimal
    best_trade: Decimal
    worst_trade: Decimal


class EquityPoint(BaseModel):
    timestamp: datetime
    cumulative_pnl: Decimal
    trade_pnl: Decimal
    symbol: str
    side: str


class DailyPnlPoint(BaseModel):
    date: str           # "YYYY-MM-DD"
    daily_pnl: Decimal
    cumulative_pnl: Decimal
    trade_count: int = 0


class AnalyticsSummaryResponse(BaseModel):
    global_stats: TradeSummary
    by_bot: list[BotStats]
    equity_curve: list[EquityPoint]


class ActivityPoint(BaseModel):
    date: str           # "YYYY-MM-DD"
    count: int          # número de trades
    pnl: Decimal        # PnL del día


class HourlyStats(BaseModel):
    hour: int           # 0-23
    trades: int
    wins: int
    pnl: Decimal
    win_rate: float
