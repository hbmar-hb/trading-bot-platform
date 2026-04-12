import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class TradeSummary(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float                 # 0.0 – 1.0
    total_pnl: Decimal
    average_pnl: Decimal
    best_trade: Decimal
    worst_trade: Decimal


class BotStats(BaseModel):
    bot_id: uuid.UUID
    bot_name: str
    symbol: str
    status: str
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl: Decimal


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


class AnalyticsSummaryResponse(BaseModel):
    global_stats: TradeSummary
    by_bot: list[BotStats]
    equity_curve: list[EquityPoint]
