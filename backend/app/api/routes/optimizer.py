"""
Optimizador de parámetros por bot.

Analiza el histórico de posiciones cerradas y señales de un bot y propone:
- Stop loss inicial óptimo        (basado en volatilidad real + ratio R:R)
- Take profits escalonados        (basado en alcanzabilidad + profit factor)
- Apalancamiento recomendado      (basado en volatilidad y win rate)
- Trailing stop                   (basado en duración de ganadores)
- Breakeven                       (basado en tasa de SL y duración)
- Stop dinámico                   (basado en patrones de winners largos)
- Confirmación de señal (min)     (basado en SL rápidos + win rate)
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loguru import logger

from app.api.dependencies import get_current_user_id
from app.models.bot_config import BotConfig
from app.models.exchange_trade import ExchangeTrade
from app.models.position import Position
from app.models.signal_log import SignalLog
from app.services.database import get_db

router = APIRouter(prefix="/optimizer", tags=["optimizer"])

MIN_TRADES = 3  # Mínimo de trades para sugerencias fiables (reducido de 5 a 3)


@dataclass
class _TradeView:
    """Vista enriquecida de un trade para análisis, combinando ExchangeTrade + Position."""
    realized_pnl: Decimal
    entry_price: Decimal | None
    quantity: Decimal
    side: str
    opened_at: datetime | None
    closed_at: datetime | None


@router.get("/{bot_id}")
async def get_optimizer(
    bot_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    bot_result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user_id)
    )
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")

    # Fuente PRIMARIA: exchange_trades (datos reales del exchange - más fiables)
    # Fallback: posiciones del bot si no hay exchange_trades
    from sqlalchemy import or_
    
    symbol_base = bot.symbol.split('/')[0] if '/' in bot.symbol else bot.symbol
    
    trades_result = await db.execute(
        select(ExchangeTrade).where(
            ExchangeTrade.user_id == user_id,
            ExchangeTrade.bot_id == bot_id,
            ExchangeTrade.source == "bot",
            ExchangeTrade.closed_at.is_not(None),
            ExchangeTrade.realized_pnl.is_not(None),
        ).order_by(ExchangeTrade.closed_at)
    )
    trades = trades_result.scalars().all()
    
    # También obtener posiciones para enriquecimiento y debug
    pos_result = await db.execute(
        select(Position).where(
            Position.bot_id == bot_id,
            Position.status == "closed",
            Position.realized_pnl.is_not(None),
        ).order_by(Position.opened_at)
    )
    positions = pos_result.scalars().all()
    
    # Debug info
    logger.info(f"[OPTIMIZER] Bot {bot.bot_name} ({bot.symbol}): {len(positions)} posiciones, {len(trades)} trades del bot")
    print(f"[OPTIMIZER DEBUG] Bot {bot.bot_name} ({bot.symbol}): positions={len(positions)}, bot_trades={len(trades)}", flush=True)

    if len(trades) >= MIN_TRADES:
        # Usar exchange_trades como fuente principal (más fiable)
        position_ids = {t.position_id for t in trades if t.position_id}
        positions_by_id: dict = {}
        if position_ids:
            enrich_result = await db.execute(
                select(Position).where(Position.id.in_(position_ids))
            )
            positions_by_id = {p.id: p for p in enrich_result.scalars().all()}

        trade_views: list[_TradeView] = [
            _TradeView(
                realized_pnl=t.realized_pnl,
                entry_price=t.entry_price or (positions_by_id[t.position_id].entry_price if t.position_id in positions_by_id else None),
                quantity=t.quantity,
                side=(positions_by_id[t.position_id].side if t.position_id in positions_by_id else t.side) or "long",
                opened_at=t.opened_at or (positions_by_id[t.position_id].opened_at if t.position_id in positions_by_id else None),
                closed_at=t.closed_at,
            )
            for t in trades
        ]
    elif len(positions) >= MIN_TRADES:
        # Fallback: usar posiciones si no hay suficientes exchange_trades
        trade_views = [
            _TradeView(
                realized_pnl=p.realized_pnl,
                entry_price=p.entry_price,
                quantity=p.quantity,
                side=p.side,
                opened_at=p.opened_at,
                closed_at=p.closed_at,
            )
            for p in positions
        ]
    else:
        # Ni trades ni posiciones suficientes
        trade_views = []

    sig_result = await db.execute(
        select(SignalLog).where(
            SignalLog.bot_id == bot_id,
            SignalLog.signal_action.in_(["long", "short"]),
        )
    )
    signals = sig_result.scalars().all()

    analysis = _analyze_trades(trade_views, signals)
    suggestions = _suggest(bot, analysis)
    
    # Info de debug para troubleshooting
    trades_count = len(trades) if 'trades' in locals() else 0
    symbol_searched = bot.symbol.split('/')[0] if '/' in bot.symbol else bot.symbol
    
    if len(trades) >= MIN_TRADES:
        data_source = "exchange_trades"
    elif len(positions) >= MIN_TRADES:
        data_source = "positions"
    else:
        data_source = "insufficient"
    
    # Calcular cooldown del optimizer (3 trades de histórico después de aplicar)
    COOLDOWN_TRADES = 3
    current_trade_count = len(trade_views)
    last_applied_count = bot.optimizer_trades_at_apply or 0
    trades_since_apply = max(0, current_trade_count - last_applied_count)
    cooldown_active = trades_since_apply < COOLDOWN_TRADES and bot.optimizer_applied_at is not None
    
    debug_info = {
        "positions_count": len(positions),
        "trades_count": trades_count,
        "trade_views_count": len(trade_views),
        "min_required": MIN_TRADES,
        "symbol": bot.symbol,
        "symbol_searched": symbol_searched,
        "data_source": data_source,
    }

    return {
        "bot_id": str(bot_id),
        "bot_name": bot.bot_name,
        "symbol": bot.symbol,
        "timeframe": bot.timeframe,
        "insufficient_data": len(trade_views) < MIN_TRADES,
        "cooldown": {
            "active": cooldown_active,
            "trades_since_apply": trades_since_apply,
            "trades_needed": COOLDOWN_TRADES,
            "last_applied_at": bot.optimizer_applied_at.isoformat() if bot.optimizer_applied_at else None,
            "applied_params": bot.optimizer_applied_params or {},
        },
        "debug": debug_info,
        "analysis": analysis,
        "current": {
            "signal_confirmation_minutes": bot.signal_confirmation_minutes,
            "initial_sl_percentage":       float(bot.initial_sl_percentage),
            "take_profits":                bot.take_profits,
            "leverage":                    bot.leverage,
            "trailing_config":             bot.trailing_config,
            "breakeven_config":            bot.breakeven_config,
            "dynamic_sl_config":           bot.dynamic_sl_config,
        },
        "suggestions": suggestions if not cooldown_active else {},
    }


# ─── Motor de análisis ────────────────────────────────────────

def _analyze_trades(trades: list, signals: list) -> dict:
    """Analiza trades desde exchange_trades (fuente unificada)."""
    if not trades:
        return _empty_analysis()

    pnls = [t.realized_pnl for t in trades if t.realized_pnl is not None]
    total = len(pnls)
    if total == 0:
        return _empty_analysis()

    winners = [t for t in trades if t.realized_pnl and t.realized_pnl > 0]
    losers  = [t for t in trades if t.realized_pnl and t.realized_pnl <= 0]
    n_win   = len(winners)
    n_loss  = len(losers)
    win_rate = round(n_win / total, 4)

    avg_win  = float(sum(t.realized_pnl for t in winners) / n_win)  if n_win  else 0.0
    avg_loss = float(sum(t.realized_pnl for t in losers)  / n_loss) if n_loss else 0.0

    total_win_abs  = float(sum(t.realized_pnl for t in winners)) if winners else 0.0
    total_loss_abs = abs(float(sum(t.realized_pnl for t in losers))) if losers else 0.0
    profit_factor  = round(total_win_abs / total_loss_abs, 2) if total_loss_abs > 0 else None

    # Duración (usando opened_at y closed_at de ExchangeTrade)
    def _hours(trade):
        if trade.opened_at and trade.closed_at:
            return (trade.closed_at - trade.opened_at).total_seconds() / 3600
        return None

    win_durations  = [h for t in winners if (h := _hours(t)) is not None]
    loss_durations = [h for t in losers  if (h := _hours(t)) is not None]
    all_durations  = win_durations + loss_durations

    avg_duration     = round(sum(all_durations)  / len(all_durations),  1) if all_durations  else 0.0
    avg_winner_hours = round(sum(win_durations)  / len(win_durations),  1) if win_durations  else 0.0
    avg_loser_hours  = round(sum(loss_durations) / len(loss_durations), 1) if loss_durations else 0.0

    # Movimiento de precio real
    price_moves = []
    win_price_moves = []
    loss_price_moves = []
    for t in trades:
        entry = float(t.entry_price or 0)
        qty   = float(t.quantity or 0)
        pnl   = float(t.realized_pnl or 0)
        if entry > 0 and qty > 0:
            exit_price = entry + pnl / qty if t.side == "long" else entry - pnl / qty
            move_pct = abs(exit_price - entry) / entry * 100
            price_moves.append(move_pct)
            if pnl > 0:
                win_price_moves.append(move_pct)
            else:
                loss_price_moves.append(move_pct)
    
    # Para exchange_trades, no tenemos SL/TP configurados, así que estimamos
    # basándonos en el movimiento real de los perdedores
    avg_sl_pct = round(sum(loss_price_moves) / len(loss_price_moves), 2) if loss_price_moves else 0.0
    sl_hits = n_loss  # Asumimos que todos los perdedores tocaron SL
    sl_hit_rate = round(sl_hits / n_loss, 4) if n_loss > 0 else 0.0
    
    # TP estimado basado en ganadores
    avg_tp1_target = round(sum(win_price_moves) / len(win_price_moves), 2) if win_price_moves else None
    tp1_reach_rate = 1.0 if n_win > 0 else 0.0  # Los ganadores alcanzaron su objetivo
    
    # Señales canceladas por filtro anti-falso
    total_signals = len(signals)
    cancelled = sum(
        1 for s in signals
        if s.error_message and (
            "cancelad" in s.error_message.lower() or
            "falsa"    in s.error_message.lower() or
            "ignor"    in s.error_message.lower()
        )
    )
    cancel_rate = round(cancelled / total_signals, 4) if total_signals > 0 else 0.0

    return {
        "total_closed":          total,
        "winning":               n_win,
        "losing":                n_loss,
        "win_rate":              win_rate,
        "profit_factor":         profit_factor,
        "real_rr":               round((sum(win_price_moves)/len(win_price_moves)) / (sum(loss_price_moves)/len(loss_price_moves)), 2) if win_price_moves and loss_price_moves else None,
        "avg_win_pnl":           round(avg_win,  2),
        "avg_loss_pnl":          round(avg_loss, 2),
        "avg_win_pct":           round(sum(win_price_moves) / len(win_price_moves), 2) if win_price_moves else 0.0,
        "avg_loss_pct":          round(sum(loss_price_moves) / len(loss_price_moves), 2) if loss_price_moves else 0.0,
        "avg_price_move_pct":    round(sum(price_moves) / len(price_moves), 2) if price_moves else 0.0,
        "avg_win_price_move_pct":round(sum(win_price_moves) / len(win_price_moves), 2) if win_price_moves else 0.0,
        "avg_duration_hours":    avg_duration,
        "avg_winner_hours":      avg_winner_hours,
        "avg_loser_hours":       avg_loser_hours,
        "sl_hit_count":          sl_hits,
        "sl_hit_rate":           sl_hit_rate,
        "avg_sl_pct":            avg_sl_pct,
        "avg_tp1_target":        avg_tp1_target,
        "tp1_reach_rate":        tp1_reach_rate,
        "signals_total":         total_signals,
        "signals_cancelled":     cancelled,
        "signals_cancel_rate":   cancel_rate,
    }


def _empty_analysis() -> dict:
    return {
        "total_closed": 0, "winning": 0, "losing": 0, "win_rate": 0.0,
        "profit_factor": None, "real_rr": None,
        "avg_win_pnl": 0.0, "avg_loss_pnl": 0.0,
        "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
        "avg_price_move_pct": 0.0, "avg_win_price_move_pct": 0.0,
        "avg_duration_hours": 0.0, "avg_winner_hours": 0.0, "avg_loser_hours": 0.0,
        "sl_hit_count": 0, "sl_hit_rate": 0.0, "avg_sl_pct": 0.0,
        "avg_tp1_target": None, "tp1_reach_rate": None,
        "signals_total": 0, "signals_cancelled": 0, "signals_cancel_rate": 0.0,
    }


# ─── Motor de sugerencias ─────────────────────────────────────

def _suggest(bot: BotConfig, a: dict) -> dict:
    if a["total_closed"] == 0:
        return {}

    win_rate         = a["win_rate"]
    profit_factor    = a["profit_factor"] or 1.0
    avg_sl_pct       = a["avg_sl_pct"]
    sl_hit_rate      = a["sl_hit_rate"]
    avg_win_pct      = a["avg_win_pct"]
    avg_loss_pct     = a["avg_loss_pct"]
    avg_price_move   = a["avg_price_move_pct"]
    avg_winner_hours = a["avg_winner_hours"]
    avg_loser_hours  = a["avg_loser_hours"]
    cancel_rate      = a["signals_cancel_rate"]
    real_rr          = a["real_rr"]
    avg_tp1_target   = a["avg_tp1_target"]
    tp1_reach_rate   = a["tp1_reach_rate"]

    current_sl   = float(bot.initial_sl_percentage)
    current_conf = bot.signal_confirmation_minutes or 0
    current_lev  = bot.leverage
    tr  = bot.trailing_config  or {}
    be  = bot.breakeven_config or {}
    dy  = bot.dynamic_sl_config or {}

    suggestions: dict = {}

    # ── Volatilidad del activo (clasificación interna) ─────────
    # Usa el movimiento medio real de precio entre entrada y salida
    if avg_price_move > 5:
        volatility = "muy_alta"
    elif avg_price_move > 3:
        volatility = "alta"
    elif avg_price_move > 1.5:
        volatility = "media"
    else:
        volatility = "baja"

    # ── Apalancamiento ─────────────────────────────────────────
    # El apalancamiento seguro depende de la volatilidad real del activo
    # y del ratio R:R. Si el activo se mueve mucho, apalancamiento alto = riesgo de liquidación.
    vol_max_lev = {"muy_alta": 3, "alta": 5, "media": 10, "baja": 20}[volatility]

    # Criterio Kelly: f* = W/L - (1-W)/(W/L)
    wl_ratio = avg_win_pct / avg_loss_pct if avg_loss_pct > 0 else 1.0
    kelly    = win_rate - (1 - win_rate) / wl_ratio if wl_ratio > 0 else -1

    if kelly <= 0 or (win_rate < 0.4 and profit_factor < 1.2):
        kelly_lev = max(1, current_lev - 2)
        lev_direction = "reducir"
        lev_reason_extra = (
            f"Kelly negativo con win rate {int(win_rate*100)}% y ratio G/P {wl_ratio:.1f}x. "
            "El histórico indica que el edge no soporta el apalancamiento actual."
        )
    elif win_rate >= 0.60 and profit_factor >= 1.8 and kelly > 0.1:
        kelly_lev = min(vol_max_lev, current_lev + 2)
        lev_direction = "subir"
        lev_reason_extra = (
            f"Win rate {int(win_rate*100)}% con profit factor {profit_factor:.1f}x y Kelly positivo. "
            "El histórico soporta más apalancamiento dentro del límite de volatilidad."
        )
    else:
        kelly_lev = current_lev
        lev_direction = "mantener"
        lev_reason_extra = (
            f"Win rate {int(win_rate*100)}% y profit factor {profit_factor:.1f}x. "
            "El apalancamiento actual es coherente con el rendimiento histórico."
        )

    new_lev = min(kelly_lev, vol_max_lev)

    vol_labels = {
        "muy_alta": f"muy alta ({avg_price_move:.1f}% de movimiento medio)",
        "alta":     f"alta ({avg_price_move:.1f}% de movimiento medio)",
        "media":    f"media ({avg_price_move:.1f}% de movimiento medio)",
        "baja":     f"baja ({avg_price_move:.1f}% de movimiento medio)",
    }
    suggestions["leverage"] = {
        "value": new_lev,
        "reason": (
            f"Volatilidad del activo {vol_labels[volatility]} → máximo recomendado {vol_max_lev}x. "
            f"{lev_reason_extra}"
        ),
    }

    # ── Stop Loss ──────────────────────────────────────────────
    # El SL ideal equilibra dos fuerzas:
    #   1. Suficientemente amplio para no ser tocado por ruido de mercado
    #   2. Suficientemente ajustado para que la pérdida sea menor que la ganancia (R:R ≥ 1.5)
    # SL máximo según R:R: si queremos R:R ≥ 1.5 y el activo mueve ~avg_win_pct en ganadores,
    #   sl_max = avg_win_pct / 1.5
    # SL mínimo según ruido: debe superar el movimiento típico adverso (avg_price_move de losers)

    target_rr = 1.5
    sl_by_rr  = round(avg_win_pct / target_rr, 2) if avg_win_pct > 0 else current_sl
    # Usar la media real de distancia al SL como referencia base
    sl_base   = avg_sl_pct if avg_sl_pct > 0 else current_sl

    if sl_hit_rate > 0.5 and win_rate < 0.5:
        # Muchos SL → SL demasiado ajustado, ampliar
        new_sl = round(min(sl_base * 1.25, sl_by_rr * 1.1), 2)
        sl_reason = (
            f"El {int(sl_hit_rate*100)}% de las pérdidas tocaron el SL — "
            f"distancia media actual {sl_base:.1f}%. "
            "Ampliar evita salidas prematuras por ruido de mercado."
        )
    elif real_rr is not None and real_rr < 1.0:
        # R:R real < 1 → incluso ganando no se compensa → ajustar SL
        new_sl = round(min(sl_by_rr, sl_base), 2)
        sl_reason = (
            f"Ratio R:R real {real_rr:.1f}x — las ganancias ({avg_win_pct:.1f}%) no compensan "
            f"las pérdidas ({avg_loss_pct:.1f}%). Ajustar el SL a {new_sl:.1f}% para mejorar el ratio."
        )
    elif win_rate > 0.65 and sl_hit_rate < 0.2:
        # Buen win rate con pocos SL → se puede ajustar levemente para mejorar R:R
        new_sl = round(max(0.3, sl_base * 0.9), 2)
        sl_reason = (
            f"Win rate {int(win_rate*100)}% con solo {int(sl_hit_rate*100)}% de pérdidas por SL. "
            "Ajustar ligeramente mejora el ratio riesgo/beneficio."
        )
    else:
        new_sl = round(sl_base, 2) if sl_base > 0 else current_sl
        sl_reason = (
            f"Distancia media real al SL: {sl_base:.1f}%. "
            "Alinear el SL con el comportamiento real del activo."
        )

    suggestions["initial_sl_percentage"] = {
        "value": max(0.1, new_sl),
        "reason": sl_reason,
    }

    # ── Take Profits ───────────────────────────────────────────
    # Lógica de alcanzabilidad:
    #   - Si tp1_reach_rate < 40% → el TP1 es muy alto, el precio no llega
    #   - Si tp1_reach_rate > 80% → TP1 muy bajo, dejando dinero en la mesa
    #   - Objetivo: TP1 que el precio alcance en ~60–70% de ganadores
    # Además: TP1 debe cumplir R:R ≥ 1.5 respecto al SL sugerido

    new_sl_for_rr = suggestions["initial_sl_percentage"]["value"]
    min_tp1_for_rr = round(new_sl_for_rr * target_rr, 2)  # TP1 mínimo para R:R 1.5:1

    if avg_win_pct > 0:
        # TP1 objetivo: el movimiento real medio de ganadores
        tp1_base = max(min_tp1_for_rr, round(avg_win_pct * 0.50, 1))
        tp2_base = max(tp1_base + 0.3, round(avg_win_pct * 0.85, 1))
        tp3_base = max(tp2_base + 0.3, round(avg_win_pct * 1.30, 1))

        if tp1_reach_rate is not None and avg_tp1_target is not None:
            if tp1_reach_rate < 0.35:
                # TP1 actual muy alto — no se alcanza → bajar
                tp1_base = round(max(min_tp1_for_rr, avg_win_pct * 0.45), 1)
                tp_reason_prefix = (
                    f"El TP1 configurado ({avg_tp1_target:.1f}%) solo se alcanzó en el "
                    f"{int(tp1_reach_rate*100)}% de ganadores — demasiado alto. "
                )
            elif tp1_reach_rate > 0.80:
                # TP1 se alcanza casi siempre → puede subirse para capturar más
                tp1_base = round(max(min_tp1_for_rr, avg_win_pct * 0.60), 1)
                tp_reason_prefix = (
                    f"El TP1 ({avg_tp1_target:.1f}%) se alcanzó en el {int(tp1_reach_rate*100)}% "
                    "de ganadores — hay margen para subir y capturar más beneficio. "
                )
            else:
                tp_reason_prefix = (
                    f"TP1 actual ({avg_tp1_target:.1f}%) alcanzado en {int(tp1_reach_rate*100)}% "
                    "de ganadores — ratio aceptable. Ajuste fino basado en movimiento histórico. "
                )
        else:
            tp_reason_prefix = (
                f"Movimiento medio de ganadores: {avg_win_pct:.1f}%. "
            )

        tp_value = [
            {"profit_percent": round(tp1_base, 1), "close_percent": 30.0},
            {"profit_percent": round(tp2_base, 1), "close_percent": 40.0},
        ]
        if tp3_base > tp2_base + 0.3:
            tp_value.append({"profit_percent": round(tp3_base, 1), "close_percent": 30.0})

        suggestions["take_profits"] = {
            "value": tp_value,
            "reason": (
                f"{tp_reason_prefix}"
                f"TPs en {tp1_base:.1f}% (30%), {tp2_base:.1f}% (40%) y {tp3_base:.1f}% (30%). "
                f"TP1 mínimo para R:R 1.5:1 con SL {new_sl_for_rr:.1f}%: {min_tp1_for_rr:.1f}%."
            ),
        }

    # ── Trailing Stop ──────────────────────────────────────────
    # Útil cuando los ganadores corren durante horas — protege ganancias en tendencias largas.
    # Activar si: ganadores duran >8h Y profit factor es razonable.
    tr_enabled = tr.get("enabled", False)
    if avg_winner_hours > 8 and profit_factor >= 1.3:
        # Activación: cuando el precio ya está en ~40% del movimiento medio ganador
        activation = round(max(0.3, avg_win_pct * 0.40), 1)
        # Callback: ~30% del movimiento medio (permite respirar sin cerrar demasiado pronto)
        callback = round(max(0.2, avg_win_pct * 0.30), 1)
        suggestions["trailing_config"] = {
            "value": {"enabled": True, "activation_profit": activation, "callback_rate": callback},
            "reason": (
                f"Los ganadores duran de media {avg_winner_hours:.1f}h — patrón de tendencia. "
                f"El trailing activa al {activation:.1f}% de ganancia y cierra si retrocede {callback:.1f}%, "
                "capturando el grueso del movimiento sin salir demasiado pronto."
            ),
        }
    elif tr_enabled and avg_winner_hours < 4:
        # Trailing activo pero trades son cortos → podría cerrar demasiado pronto
        suggestions["trailing_config"] = {
            "value": {"enabled": False, "activation_profit": tr.get("activation_profit", 0), "callback_rate": tr.get("callback_rate", 0)},
            "reason": (
                f"Los ganadores duran solo {avg_winner_hours:.1f}h de media. "
                "El trailing puede cerrar posiciones antes de tiempo en movimientos rápidos — "
                "considera desactivarlo y usar TPs fijos."
            ),
        }

    # ── Breakeven ──────────────────────────────────────────────
    # Útil cuando hay muchos SL hit y las pérdidas son frecuentes.
    # Mover SL a entrada (o con pequeño lock) una vez el precio está a favor.
    be_enabled = be.get("enabled", False)
    if sl_hit_rate > 0.4 and not be_enabled:
        # Activación conservadora: cuando el precio se mueve ~30% del ganador medio
        be_activation = round(max(0.2, avg_win_pct * 0.30), 1)
        be_lock       = round(max(0.05, avg_win_pct * 0.05), 2)
        suggestions["breakeven_config"] = {
            "value": {"enabled": True, "activation_profit": be_activation, "lock_profit": be_lock},
            "reason": (
                f"El {int(sl_hit_rate*100)}% de las pérdidas tocaron el SL. "
                f"Activar breakeven al {be_activation:.1f}% de ganancia asegura que las posiciones "
                "que arrancan bien no terminen en pérdida — reduce el impacto de los SL."
            ),
        }
    elif be_enabled and sl_hit_rate < 0.15 and win_rate > 0.65:
        suggestions["breakeven_config"] = {
            "value": {"enabled": False, "activation_profit": be.get("activation_profit", 0), "lock_profit": be.get("lock_profit", 0)},
            "reason": (
                f"Pocos SL hit ({int(sl_hit_rate*100)}%) con win rate {int(win_rate*100)}%. "
                "El breakeven puede estar cerrando posiciones en pullbacks antes de que se desarrollen. "
                "El histórico no justifica tenerlo activo."
            ),
        }

    # ── Stop Dinámico ──────────────────────────────────────────
    # Mueve el SL en pasos a medida que el precio avanza.
    # Útil cuando los ganadores tienen recorrido largo y se quiere asegurar parcialmente.
    dy_enabled = dy.get("enabled", False)
    if avg_winner_hours > 12 and profit_factor >= 1.5 and not dy_enabled:
        # Paso: cada vez que el precio avanza 1 SL de distancia, mover el SL un paso
        step = round(max(0.2, avg_sl_pct * 0.5), 1)
        suggestions["dynamic_sl_config"] = {
            "value": {"enabled": True, "step_percent": step, "max_steps": 4},
            "reason": (
                f"Ganadores con recorrido largo ({avg_winner_hours:.1f}h de media) y "
                f"profit factor {profit_factor:.1f}x. El stop dinámico mueve el SL "
                f"{step:.1f}% por paso (hasta 4 pasos), asegurando ganancias progresivamente "
                "sin cerrar demasiado pronto."
            ),
        }
    elif dy_enabled and avg_winner_hours < 6:
        suggestions["dynamic_sl_config"] = {
            "value": {"enabled": False, "step_percent": dy.get("step_percent", 0), "max_steps": dy.get("max_steps", 0)},
            "reason": (
                f"Ganadores duran {avg_winner_hours:.1f}h de media — movimientos cortos. "
                "El stop dinámico puede cortar posiciones antes de llegar al objetivo. "
                "Considera desactivarlo con este perfil de operativa."
            ),
        }

    # ── Confirmación de señal ──────────────────────────────────
    # Patrón de señal falsa: SL rápidos (< 4h) + tasa alta
    sl_false_signal = sl_hit_rate > 0.4 and avg_loser_hours < 4

    if sl_false_signal and current_conf == 0:
        new_conf = 2
        conf_reason = (
            f"El {int(sl_hit_rate*100)}% de las pérdidas tocaron el SL en menos de "
            f"{avg_loser_hours:.1f}h de media — señal de entradas falsas que revierten rápido. "
            "Un delay de 2 min puede filtrarlas antes de ejecutar."
        )
    elif sl_false_signal and current_conf > 0:
        new_conf = min(current_conf + 1, 5)
        conf_reason = (
            f"Siguen apareciendo SL rápidos ({int(sl_hit_rate*100)}%, media {avg_loser_hours:.1f}h). "
            f"El delay de {current_conf} min no es suficiente — probar {new_conf} min."
        )
    elif win_rate < 0.45 and current_conf == 0:
        new_conf = 2
        conf_reason = (
            f"Win rate del {int(win_rate*100)}% con confirmación en 0 min. "
            "Un delay de 2 min puede filtrar señales que revierten antes de desarrollarse."
        )
    elif win_rate < 0.45 and current_conf > 0:
        new_conf = min(current_conf + 1, 5)
        conf_reason = (
            f"Win rate bajo ({int(win_rate*100)}%) incluso con delay. "
            f"Aumentar a {new_conf} min podría mejorar la calidad de entradas."
        )
    elif cancel_rate > 0.25:
        new_conf = max(1, current_conf)
        conf_reason = (
            f"El filtro ya canceló el {int(cancel_rate*100)}% de señales — está funcionando. "
            "Mantener o aumentar si el win rate no mejora."
        )
    elif win_rate >= 0.60 and not sl_false_signal and current_conf > 2:
        new_conf = max(0, current_conf - 1)
        conf_reason = (
            f"Win rate del {int(win_rate*100)}% con pocos SL rápidos. "
            "Podrías reducir el delay para capturar más entradas."
        )
    else:
        new_conf = current_conf
        conf_reason = "El delay actual es coherente con el rendimiento histórico del bot."

    suggestions["signal_confirmation_minutes"] = {
        "value": new_conf,
        "reason": conf_reason,
    }

    return suggestions


# ─── Endpoint para aplicar sugerencias ─────────────────────────

@router.post("/{bot_id}/apply")
async def apply_optimizer_suggestions(
    bot_id: uuid.UUID,
    payload: dict,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Aplica sugerencias del optimizer al bot y registra el estado para cooldown.
    
    Payload: { "params": { "initial_sl_percentage": 1.5, ... } }
    """
    # Obtener bot
    bot_result = await db.execute(
        select(BotConfig).where(
            BotConfig.id == bot_id,
            BotConfig.user_id == user_id
        )
    )
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")
    
    applied_params = payload.get("params", {})
    if not applied_params:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se proporcionaron parámetros")
    
    # Contar trades actuales del bot
    trades_result = await db.execute(
        select(ExchangeTrade).where(
            ExchangeTrade.bot_id == bot_id,
            ExchangeTrade.source == "bot",
            ExchangeTrade.closed_at.is_not(None),
        )
    )
    trades = trades_result.scalars().all()
    current_trade_count = len(trades)
    
    # Actualizar bot con los parámetros aplicados
    for key, value in applied_params.items():
        if hasattr(bot, key):
            # Convertir tipos si es necesario
            if key == "initial_sl_percentage" and isinstance(value, (int, float)):
                value = Decimal(str(value))
            setattr(bot, key, value)
    
    # Registrar estado del optimizer para cooldown
    from datetime import timezone
    bot.optimizer_applied_at = datetime.now(timezone.utc)
    bot.optimizer_trades_at_apply = current_trade_count
    bot.optimizer_applied_params = applied_params
    
    await db.commit()
    
    logger.info(f"[OPTIMIZER] Bot {bot.bot_name}: aplicados {len(applied_params)} parámetros. Trades en momento: {current_trade_count}")
    
    return {
        "message": "Parámetros aplicados correctamente",
        "applied_params": applied_params,
        "trades_at_apply": current_trade_count,
        "cooldown_until": current_trade_count + 3,
    }
