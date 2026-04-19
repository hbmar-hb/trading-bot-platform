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
from datetime import datetime, timezone
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



# ═══════════════════════════════════════════════════════════════════════════
# AUTO-OPTIMIZACIÓN INTELIGENTE
# ═══════════════════════════════════════════════════════════════════════════

# ─── Niveles de confianza por cantidad de trades ───────────────────────────

CONFIDENCE_LEVELS = {
    50: {"name": "muy_alta", "factor": 1.00, "label": "Confianza total", "color": "green"},
    20: {"name": "alta",     "factor": 0.90, "label": "Confiado",       "color": "green"},
    10: {"name": "media",    "factor": 0.70, "label": "Moderado",       "color": "yellow"},
    5:  {"name": "baja",     "factor": 0.50, "label": "Conservador",    "color": "orange"},
    3:  {"name": "muy_baja", "factor": 0.20, "label": "Muy conservador", "color": "red"},
}

# ─── Límites Absolutos de Seguridad ───────────────────────────────────────
# Nunca permitir valores fuera de estos rangos
SAFETY_LIMITS = {
    "initial_sl_percentage": {"min": 0.3, "max": 8.0},  # SL entre 0.3% y 8%
    "leverage": {"min": 1, "max": 25},                  # Leverage 1x-25x
    "signal_confirmation_minutes": {"min": 0, "max": 10}, # 0-10 minutos
    "take_profits": {"min_tp": 0.5, "max_tp": 50.0},    # TP entre 0.5% y 50%
}

# ─── Zona de Confort ─────────────────────────────────────────────────────
# Si todos los indicadores están en estos rangos, no hacer cambios
COMFORT_ZONE = {
    "win_rate": (0.55, 0.75),        # 55-75% win rate
    "profit_factor": (1.5, 3.0),     # PF entre 1.5 y 3
    "sl_hit_rate": (0.30, 0.50),     # SL hit entre 30-50%
    "real_rr": (1.2, 2.0),           # R:R entre 1.2 y 2.0
}

# ─── Umbrales Adaptativos por Volatilidad del Activo ─────────────────────
# Símbolos volátiles (memes, altcoins pequeñas) tienen umbrales más permisivos
VOLATILITY_PROFILES = {
    # Perfil: Extremo (nuevas memecoins, muy volátiles)
    "extreme": {
        "symbols": ["FLOKI", "BONK", "WIF", "PEPE2", "BABYDOGE", "ELON", "SAMO", "DOBO"],
        "thresholds": {
            "win_rate_green": 0.45,      # 45% (muy tolerante)
            "win_rate_yellow": 0.35,
            "sl_hit_green": 0.70,        # Muy tolerante con SL hits
            "sl_hit_yellow": 0.85,
            "pf_green": 1.2,             # PF muy permisivo
            "pf_yellow": 0.8,
        }
    },
    # Perfil: Volátil (memes, low-cap alts)
    "volatile": {
        "symbols": ["PEPE", "SHIB", "DOGE", "MOG", "1000PEPE", "1000SHIB", "1000FLOKI"],
        "thresholds": {
            "win_rate_green": 0.50,      # 50% (más bajo por volatilidad)
            "win_rate_yellow": 0.40,
            "sl_hit_green": 0.60,        # Más tolerante con SL hits
            "sl_hit_yellow": 0.75,
            "pf_green": 1.3,             # PF más permisivo
            "pf_yellow": 0.9,
        }
    },
    # Perfil: Moderado (alts medianas)
    "moderate": {
        "symbols": ["SOL", "AVAX", "MATIC", "LINK", "UNI", "AAVE", "LDO", "CRV"],
        "thresholds": {
            "win_rate_green": 0.52,
            "win_rate_yellow": 0.42,
            "sl_hit_green": 0.55,
            "sl_hit_yellow": 0.70,
            "pf_green": 1.4,
            "pf_yellow": 0.95,
        }
    },
    # Perfil: Estable (BTC, ETH, stable pairs)
    "stable": {
        "symbols": ["BTC", "ETH", "BNB", "XRP", "ADA"],
        "thresholds": {
            "win_rate_green": 0.55,
            "win_rate_yellow": 0.45,
            "sl_hit_green": 0.50,
            "sl_hit_yellow": 0.70,
            "pf_green": 1.5,
            "pf_yellow": 1.0,
        }
    }
}

def _get_volatility_profile(symbol: str) -> dict:
    """Retorna el perfil de volatilidad para un símbolo dado."""
    symbol_upper = symbol.upper().replace("USDT", "").replace("/", "").replace(":", "")
    
    for profile_name, profile in VOLATILITY_PROFILES.items():
        if any(sym in symbol_upper for sym in profile["symbols"]):
            return profile["thresholds"]
    
    # Default: perfil moderado
    return VOLATILITY_PROFILES["moderate"]["thresholds"]


def _is_in_comfort_zone(analysis: dict) -> tuple[bool, dict]:
    """
    Verifica si todos los indicadores están en zona de confort.
    Retorna (en_zona_confort, detalle_por_indicador)
    """
    indicators = {}
    all_in_comfort = True
    
    for key, (min_val, max_val) in COMFORT_ZONE.items():
        value = analysis.get(key, 0) or 0
        in_comfort = min_val <= value <= max_val
        indicators[key] = {
            "value": value,
            "min": min_val,
            "max": max_val,
            "in_comfort": in_comfort
        }
        if not in_comfort:
            all_in_comfort = False
    
    return all_in_comfort, indicators


def _calculate_health_score(analysis: dict) -> dict:
    """
    Calcula el score de salud del bot (0-100).
    Retorna score y nivel de salud.
    """
    score = 0
    details = {}
    
    # Win Rate (0-25 puntos)
    wr = analysis.get("win_rate", 0)
    if wr >= 0.55:
        score += 25
        details["win_rate"] = {"score": 25, "max": 25, "status": "excellent"}
    elif wr >= 0.45:
        score += 15
        details["win_rate"] = {"score": 15, "max": 25, "status": "good"}
    elif wr >= 0.35:
        score += 5
        details["win_rate"] = {"score": 5, "max": 25, "status": "poor"}
    else:
        details["win_rate"] = {"score": 0, "max": 25, "status": "critical"}
    
    # Profit Factor (0-30 puntos)
    pf = analysis.get("profit_factor") or 0
    if pf >= 1.5:
        score += 30
        details["profit_factor"] = {"score": 30, "max": 30, "status": "excellent"}
    elif pf >= 1.0:
        score += 15
        details["profit_factor"] = {"score": 15, "max": 30, "status": "good"}
    elif pf >= 0.8:
        score += 5
        details["profit_factor"] = {"score": 5, "max": 30, "status": "poor"}
    else:
        details["profit_factor"] = {"score": 0, "max": 30, "status": "critical"}
    
    # SL Hit Rate (0-25 puntos) - Menos es mejor
    sl_hit = analysis.get("sl_hit_rate", 0)
    if sl_hit <= 0.50:
        score += 25
        details["sl_hit_rate"] = {"score": 25, "max": 25, "status": "excellent"}
    elif sl_hit <= 0.65:
        score += 15
        details["sl_hit_rate"] = {"score": 15, "max": 25, "status": "good"}
    elif sl_hit <= 0.80:
        score += 5
        details["sl_hit_rate"] = {"score": 5, "max": 25, "status": "poor"}
    else:
        details["sl_hit_rate"] = {"score": 0, "max": 25, "status": "critical"}
    
    # Ratio R:R (0-20 puntos)
    rr = analysis.get("real_rr") or 0
    if rr >= 1.5:
        score += 20
        details["real_rr"] = {"score": 20, "max": 20, "status": "excellent"}
    elif rr >= 1.2:
        score += 10
        details["real_rr"] = {"score": 10, "max": 20, "status": "good"}
    elif rr >= 1.0:
        score += 5
        details["real_rr"] = {"score": 5, "max": 20, "status": "poor"}
    else:
        details["real_rr"] = {"score": 0, "max": 20, "status": "critical"}
    
    # Determinar nivel de salud
    if score >= 80:
        level = "excellent"
        message = "Bot en excelente estado - Mantener configuración actual"
        action = "none"  # No hacer cambios
    elif score >= 60:
        level = "good"
        message = "Bot funcionando bien - Micro-ajustes si es necesario"
        action = "micro"
    elif score >= 40:
        level = "fair"
        message = "Rendimiento aceptable - Ajustes moderados recomendados"
        action = "moderate"
    else:
        level = "critical"
        message = "Rendimiento deficiente - Modo crisis activado"
        action = "crisis"  # Cambios más agresivos permitidos
    
    return {
        "score": score,
        "max_score": 100,
        "level": level,
        "message": message,
        "recommended_action": action,
        "details": details,
    }


def _apply_time_decay(effectiveness: float, days_ago: float, decay_rate: float = 0.95) -> float:
    """
    Aplica decaimiento temporal a la efectividad.
    Fórmula: efectividad × (decay_rate ^ días)
    """
    if days_ago <= 0:
        return effectiveness
    return effectiveness * (decay_rate ** days_ago)


def _calculate_weighted_effectiveness(history: list) -> dict:
    """
    Calcula efectividad ponderada por confianza y decaimiento temporal.
    """
    if not history:
        return {"weighted_avg": 0, "trend": "neutral", "total_changes": 0}
    
    now = datetime.now(timezone.utc)
    weighted_sum = 0
    weight_sum = 0
    recent_scores = []
    
    for entry in history:
        if entry.get("effectiveness") is None:
            continue
        
        # Peso base por confianza
        confidence_factor = {
            "muy_alta": 1.0, "alta": 0.9, "media": 0.7,
            "baja": 0.5, "muy_baja": 0.2
        }.get(entry.get("confidence", ""), 0.5)
        
        # Aplicar decaimiento temporal
        timestamp = entry.get("timestamp", "")
        if timestamp:
            try:
                entry_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                days_ago = (now - entry_date).days
                effectiveness = _apply_time_decay(entry["effectiveness"], days_ago)
            except:
                effectiveness = entry["effectiveness"]
        else:
            effectiveness = entry["effectiveness"]
        
        # Ponderar
        weighted_sum += effectiveness * confidence_factor
        weight_sum += confidence_factor
        
        # Guardar scores recientes para tendencia
        if len(recent_scores) < 5:
            recent_scores.append(effectiveness)
    
    if weight_sum == 0:
        return {"weighted_avg": 0, "trend": "neutral", "total_changes": 0}
    
    weighted_avg = weighted_sum / weight_sum
    
    # Calcular tendencia
    trend = "neutral"
    if len(recent_scores) >= 3:
        first_half = sum(recent_scores[:len(recent_scores)//2]) / (len(recent_scores)//2)
        second_half = sum(recent_scores[len(recent_scores)//2:]) / (len(recent_scores) - len(recent_scores)//2)
        
        if second_half > first_half + 5:
            trend = "improving"
        elif second_half < first_half - 5:
            trend = "declining"
    
    return {
        "weighted_avg": round(weighted_avg, 2),
        "trend": trend,
        "total_changes": len([e for e in history if e.get("effectiveness") is not None]),
        "recent_scores": recent_scores,
    }

def _get_confidence_level(trade_count: int) -> dict:
    """Retorna nivel de confianza basado en cantidad de trades."""
    for threshold, level in sorted(CONFIDENCE_LEVELS.items(), reverse=True):
        if trade_count >= threshold:
            return level
    return {"name": "insuficiente", "factor": 0.0, "label": "Sin confianza", "color": "gray"}


# ─── Evaluación de indicadores ─────────────────────────────────────────────

def _evaluate_indicators(analysis: dict, symbol: str = "") -> dict:
    """
    Evalúa 4 indicadores clave y determina nivel de acción.
    Usa umbrales adaptativos según la volatilidad del activo.
    Retorna: {"level": 1|2|3, "name": str, "message": str, "indicators": dict}
    """
    # Obtener umbrales adaptativos según el símbolo
    thresholds = _get_volatility_profile(symbol)
    
    indicators = {}
    
    # Win Rate: usar umbrales adaptativos
    wr = analysis.get("win_rate", 0)
    wr_green = thresholds.get("win_rate_green", 0.55)
    wr_yellow = thresholds.get("win_rate_yellow", 0.45)
    
    if wr >= wr_green:
        indicators["win_rate"] = {"value": wr, "zone": "green", "score": 0}
    elif wr >= wr_yellow:
        indicators["win_rate"] = {"value": wr, "zone": "yellow", "score": 1}
    else:
        indicators["win_rate"] = {"value": wr, "zone": "red", "score": 2}
    
    # Profit Factor: usar umbrales adaptativos
    pf = analysis.get("profit_factor") or 0
    pf_green = thresholds.get("pf_green", 1.5)
    pf_yellow = thresholds.get("pf_yellow", 1.0)
    
    if pf >= pf_green:
        indicators["profit_factor"] = {"value": pf, "zone": "green", "score": 0}
    elif pf >= pf_yellow:
        indicators["profit_factor"] = {"value": pf, "zone": "yellow", "score": 1}
    else:
        indicators["profit_factor"] = {"value": pf, "zone": "red", "score": 2}
    
    # SL Hit Rate: usar umbrales adaptativos (invertido: menos es mejor)
    sl_hit = analysis.get("sl_hit_rate", 0)
    sl_green = thresholds.get("sl_hit_green", 0.50)  # <= 50% es verde
    sl_yellow = thresholds.get("sl_hit_yellow", 0.70)  # <= 70% es amarillo
    
    if sl_hit <= sl_green:
        indicators["sl_hit_rate"] = {"value": sl_hit, "zone": "green", "score": 0}
    elif sl_hit <= sl_yellow:
        indicators["sl_hit_rate"] = {"value": sl_hit, "zone": "yellow", "score": 1}
    else:
        indicators["sl_hit_rate"] = {"value": sl_hit, "zone": "red", "score": 2}
    
    # Ratio R:R: estándar (no varía mucho por volatilidad)
    rr = analysis.get("real_rr") or 0
    if rr >= 1.5:
        indicators["real_rr"] = {"value": rr, "zone": "green", "score": 0}
    elif rr >= 1.0:
        indicators["real_rr"] = {"value": rr, "zone": "yellow", "score": 1}
    else:
        indicators["real_rr"] = {"value": rr, "zone": "red", "score": 2}
    
    # Calcular nivel de acción
    total_score = sum(i["score"] for i in indicators.values())
    
    if total_score >= 4:  # 2+ rojos o equivalente
        return {
            "level": 3,
            "name": "conservador",
            "message": "Problemas graves detectados - Ajustes significativos necesarios",
            "indicators": indicators
        }
    elif total_score >= 1:  # 1 rojo o 2+ amarillos
        return {
            "level": 2,
            "name": "moderado",
            "message": "Ajustes recomendados - Algunos indicadores en zona de alerta",
            "indicators": indicators
        }
    else:  # Todo verde
        return {
            "level": 1,
            "name": "micro",
            "message": "Rendimiento óptimo - Solo micro-ajustes",
            "indicators": indicators
        }


# ─── Cálculo de cambios seguros ────────────────────────────────────────────

def _calculate_safe_change(
    current: float,
    suggested: float,
    max_change_pct: float,
    confidence_factor: float,
    min_change: float = 0.01,
    absolute_limits: dict | None = None
) -> float | None:
    """
    Calcula un cambio seguro respetando límites de confianza y límites absolutos.
    Retorna None si el cambio es menor al mínimo significativo.
    """
    if current == 0:
        result = suggested if suggested != 0 else None
    else:
        # Cambio bruto sugerido
        raw_change = suggested - current
        
        # Máximo cambio permitido por configuración
        max_change = abs(current) * (max_change_pct / 100)
        
        # Aplicar factor de confianza
        allowed_change = max_change * confidence_factor
        
        # Si el cambio sugerido es mayor al permitido, limitarlo
        if abs(raw_change) > allowed_change:
            sign = 1 if raw_change > 0 else -1
            result = round(current + (sign * allowed_change), 4)
        else:
            result = round(suggested, 4)
        
        # Si el cambio es menor al mínimo significativo, ignorarlo
        if abs(raw_change) < min_change:
            return None
    
    # Aplicar límites absolutos de seguridad si existen
    if absolute_limits and result is not None:
        min_val = absolute_limits.get("min")
        max_val = absolute_limits.get("max")
        
        if min_val is not None:
            result = max(min_val, result)
        if max_val is not None:
            result = min(max_val, result)
    
    return result


# ─── Endpoints de Auto-Optimización ────────────────────────────────────────

@router.get("/{bot_id}/auto-status")
async def get_auto_optimize_status(
    bot_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Retorna el estado actual de auto-optimización del bot."""
    bot_result = await db.execute(
        select(BotConfig).where(
            BotConfig.id == bot_id,
            BotConfig.user_id == user_id
        )
    )
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")
    
    # Contar trades actuales
    trades_result = await db.execute(
        select(ExchangeTrade).where(
            ExchangeTrade.bot_id == bot_id,
            ExchangeTrade.source == "bot",
            ExchangeTrade.closed_at.is_not(None),
        )
    )
    trades = trades_result.scalars().all()
    trade_count = len(trades)
    
    # Calcular trades desde última evaluación
    trades_since_eval = trade_count - (bot.auto_optimize_trades_at_eval or 0)
    config = bot.auto_optimize_config or {}
    reeval_after = config.get("reeval_after_trades", 5)
    
    confidence = _get_confidence_level(trade_count)
    
    return {
        "enabled": bot.auto_optimize_enabled,
        "trade_count": trade_count,
        "trades_since_eval": trades_since_eval,
        "trades_needed": max(0, reeval_after - trades_since_eval),
        "can_run": trades_since_eval >= reeval_after and trade_count >= 3,
        "confidence": confidence,
        "last_eval_at": bot.auto_optimize_last_eval_at.isoformat() if bot.auto_optimize_last_eval_at else None,
        "config": config,
        "history": bot.auto_optimize_history or [],
    }


@router.post("/{bot_id}/auto-toggle")
async def toggle_auto_optimize(
    bot_id: uuid.UUID,
    payload: dict,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Activa o desactiva la auto-optimización."""
    bot_result = await db.execute(
        select(BotConfig).where(
            BotConfig.id == bot_id,
            BotConfig.user_id == user_id
        )
    )
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")
    
    enabled = payload.get("enabled", False)
    bot.auto_optimize_enabled = enabled
    
    if enabled:
        # Inicializar contador de trades al activar
        trades_result = await db.execute(
            select(ExchangeTrade).where(
                ExchangeTrade.bot_id == bot_id,
                ExchangeTrade.source == "bot",
                ExchangeTrade.closed_at.is_not(None),
            )
        )
        trades = trades_result.scalars().all()
        bot.auto_optimize_trades_at_eval = len(trades)
        bot.auto_optimize_last_eval_at = datetime.now(timezone.utc)
    
    await db.commit()
    
    return {
        "enabled": bot.auto_optimize_enabled,
        "message": f"Auto-optimización {'activada' if enabled else 'desactivada'}"
    }


@router.post("/{bot_id}/auto-config")
async def update_auto_optimize_config(
    bot_id: uuid.UUID,
    payload: dict,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Actualiza la configuración de auto-optimización."""
    bot_result = await db.execute(
        select(BotConfig).where(
            BotConfig.id == bot_id,
            BotConfig.user_id == user_id
        )
    )
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")
    
    # Merge con configuración existente
    current_config = bot.auto_optimize_config or {}
    new_config = {**current_config, **payload}
    bot.auto_optimize_config = new_config
    
    await db.commit()
    
    return {"config": new_config}


@router.post("/{bot_id}/auto-run")
async def run_auto_optimize(
    bot_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Ejecuta el algoritmo de auto-optimización y aplica cambios si corresponde.
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
    
    # 1. Verificar si está habilitado
    if not bot.auto_optimize_enabled:
        return {"status": "disabled", "message": "Auto-optimización desactivada"}
    
    config = bot.auto_optimize_config or {}
    
    # 2. Obtener trades del bot
    trades_result = await db.execute(
        select(ExchangeTrade).where(
            ExchangeTrade.bot_id == bot_id,
            ExchangeTrade.source == "bot",
            ExchangeTrade.closed_at.is_not(None),
            ExchangeTrade.realized_pnl.is_not(None),
        ).order_by(ExchangeTrade.closed_at)
    )
    trades = trades_result.scalars().all()
    trade_count = len(trades)
    
    # 3. Verificar si hay suficientes trades nuevos desde última evaluación
    trades_since_eval = trade_count - (bot.auto_optimize_trades_at_eval or 0)
    reeval_after = config.get("reeval_after_trades", 5)
    
    if trades_since_eval < reeval_after:
        return {
            "status": "waiting",
            "message": f"Esperando {reeval_after - trades_since_eval} trades más para re-evaluar",
            "trades_since_eval": trades_since_eval,
            "trades_needed": reeval_after,
        }
    
    # 4. Obtener análisis y sugerencias
    sig_result = await db.execute(
        select(SignalLog).where(
            SignalLog.bot_id == bot_id,
            SignalLog.signal_action.in_(["long", "short"]),
        )
    )
    signals = sig_result.scalars().all()
    
    # Convertir trades a TradeView para análisis
    trade_views = [
        _TradeView(
            realized_pnl=t.realized_pnl,
            entry_price=t.entry_price,
            quantity=t.quantity,
            side=t.side or "long",
            opened_at=t.opened_at,
            closed_at=t.closed_at,
        )
        for t in trades
    ]
    
    analysis = _analyze_trades(trade_views, signals)
    suggestions = _suggest(bot, analysis)
    
    # 5. Actualizar efectividad de cambios anteriores en el historial
    history = bot.auto_optimize_history or []
    for entry in history:
        # Si tiene cambios pero no tiene métricas "after", actualizarlas
        if entry.get("changes") and entry.get("trades_after") is None:
            entry["trades_after"] = trade_count
            entry["win_rate_after"] = analysis.get("win_rate")
            entry["profit_factor_after"] = analysis.get("profit_factor")
            entry["sl_hit_rate_after"] = analysis.get("sl_hit_rate")
            entry["real_rr_after"] = analysis.get("real_rr")
            
            # Calcular efectividad general (+ positivo, - negativo)
            effectiveness = 0
            indicators_before = entry.get("indicators_before", {})
            
            # Comparar Win Rate
            if entry["win_rate_after"] and indicators_before.get("win_rate", {}).get("value"):
                wr_diff = entry["win_rate_after"] - indicators_before["win_rate"]["value"]
                effectiveness += wr_diff * 100  # 1% = 1 punto
            
            # Comparar Profit Factor
            if entry["profit_factor_after"] and indicators_before.get("profit_factor", {}).get("value"):
                pf_before = indicators_before["profit_factor"]["value"]
                pf_after = entry["profit_factor_after"]
                if pf_before > 0:
                    effectiveness += ((pf_after - pf_before) / pf_before) * 50
            
            entry["effectiveness"] = round(effectiveness, 2)
    
    bot.auto_optimize_history = history
    
    # 6. Verificar Zona de Confort
    in_comfort_zone, comfort_details = _is_in_comfort_zone(analysis)
    if in_comfort_zone:
        # Actualizar tracking pero no hacer cambios
        bot.auto_optimize_last_eval_at = datetime.now(timezone.utc)
        bot.auto_optimize_trades_at_eval = trade_count
        await db.commit()
        
        return {
            "status": "comfort_zone",
            "message": "Todos los indicadores en zona óptima - No se requieren cambios",
            "comfort_details": comfort_details,
            "trade_count": trade_count,
            "next_eval_after": trade_count + reeval_after,
        }
    
    # 6. Evaluar indicadores (con umbrales adaptativos por símbolo)
    action_eval = _evaluate_indicators(analysis, bot.symbol)
    
    # 7. Obtener nivel de confianza
    confidence = _get_confidence_level(trade_count)
    
    if confidence["factor"] == 0:
        return {
            "status": "insufficient_data",
            "message": "Se necesitan al menos 3 trades para auto-optimizar",
            "min_trades": 3,
            "current_trades": trade_count,
        }
    
    # 7b. Calcular Score de Salud
    health = _calculate_health_score(analysis)
    
    # Si el bot está en excelente estado (score >= 80), no hacer cambios
    if health["score"] >= 80:
        bot.auto_optimize_last_eval_at = datetime.now(timezone.utc)
        bot.auto_optimize_trades_at_eval = trade_count
        await db.commit()
        
        return {
            "status": "excellent_health",
            "message": f"Bot en excelente estado (Salud: {health['score']}/100) - No se requieren cambios",
            "health_score": health,
            "trade_count": trade_count,
            "next_eval_after": trade_count + reeval_after,
        }
    
    # 8. Calcular cambios seguros según nivel de acción y salud (con límites absolutos)
    # Modo crisis: si salud < 40, permitir cambios más agresivos
    is_crisis_mode = health["score"] < 40
    crisis_multiplier = 1.5 if is_crisis_mode else 1.0  # 50% más agresivo en crisis
    
    changes = {}
    
    # SL inicial (con límites absolutos 0.3% - 8%)
    if suggestions.get("initial_sl_percentage"):
        current_sl = float(bot.initial_sl_percentage)
        suggested_sl = suggestions["initial_sl_percentage"]["value"]
        max_sl_change = config.get("max_sl_change_pct", 30) * crisis_multiplier
        
        new_sl = _calculate_safe_change(
            current_sl, suggested_sl, max_sl_change, confidence["factor"],
            absolute_limits=SAFETY_LIMITS["initial_sl_percentage"]
        )
        if new_sl is not None:
            changes["initial_sl_percentage"] = new_sl
    
    # Apalancamiento (con límites absolutos 1x - 25x)
    if suggestions.get("leverage"):
        current_lev = bot.leverage
        suggested_lev = suggestions["leverage"]["value"]
        max_lev_change = config.get("max_leverage_change", 2) * crisis_multiplier
        
        # Para apalancamiento usamos cambio absoluto, no porcentual
        raw_change = suggested_lev - current_lev
        allowed_change = max_lev_change * confidence["factor"]
        
        if abs(raw_change) > allowed_change:
            sign = 1 if raw_change > 0 else -1
            new_lev = current_lev + int(sign * allowed_change)
        elif abs(raw_change) > 0:
            new_lev = suggested_lev
        else:
            new_lev = None
        
        # Aplicar límites absolutos
        if new_lev is not None:
            limits = SAFETY_LIMITS["leverage"]
            new_lev = max(limits["min"], min(limits["max"], new_lev))
            if new_lev != current_lev:
                changes["leverage"] = new_lev
    
    # Take Profits (solo si el nivel de acción es 2 o 3)
    if action_eval["level"] >= 2 and suggestions.get("take_profits"):
        # Para TPs, aplicamos el cambio proporcionalmente si todos los niveles cambian similarmente
        current_tps = bot.take_profits or []
        suggested_tps = suggestions["take_profits"]["value"]
        max_tp_change = config.get("max_tp_change_pct", 20)
        
        if len(current_tps) == len(suggested_tps) and len(current_tps) > 0:
            adjusted_tps = []
            for curr, sugg in zip(current_tps, suggested_tps):
                new_profit = _calculate_safe_change(
                    float(curr.get("profit_percent", 0)),
                    float(sugg.get("profit_percent", 0)),
                    max_tp_change,
                    confidence["factor"]
                )
                if new_profit is not None:
                    adjusted_tps.append({
                        "profit_percent": new_profit,
                        "close_percent": curr.get("close_percent", 30)
                    })
            
            if adjusted_tps:
                changes["take_profits"] = adjusted_tps
    
    # Signal confirmation (solo micro-ajustes)
    if action_eval["level"] == 1 and suggestions.get("signal_confirmation_minutes"):
        current_conf = bot.signal_confirmation_minutes
        suggested_conf = suggestions["signal_confirmation_minutes"]["value"]
        
        # Máximo cambio de 2 minutos, ajustado por confianza
        max_conf_change = 2 * confidence["factor"]
        raw_change = suggested_conf - current_conf
        
        if abs(raw_change) > max_conf_change:
            sign = 1 if raw_change > 0 else -1
            changes["signal_confirmation_minutes"] = current_conf + int(sign * max_conf_change)
        elif abs(raw_change) > 0:
            changes["signal_confirmation_minutes"] = suggested_conf
    
    # 8. Limitar a máximo 2 cambios por evaluación (prioridad: SL > Leverage > TPs > Conf)
    if len(changes) > 2:
        priority = ["initial_sl_percentage", "leverage", "take_profits", "signal_confirmation_minutes"]
        sorted_changes = sorted(changes.items(), 
                               key=lambda x: priority.index(x[0]) if x[0] in priority else 99)
        changes = dict(sorted_changes[:2])
    
    # 9. Si no hay cambios significativos, solo actualizar tracking
    if not changes:
        bot.auto_optimize_last_eval_at = datetime.now(timezone.utc)
        bot.auto_optimize_trades_at_eval = trade_count
        await db.commit()
        
        return {
            "status": "no_changes",
            "message": "No hay cambios significativos que aplicar en este momento",
            "action_level": action_eval["name"],
            "confidence": confidence["name"],
            "indicators": action_eval["indicators"],
        }
    
    # 10. Pausar bot si está activo, aplicar cambios, y reactivar
    was_active = bot.status == "active"
    
    if was_active:
        bot.status = "paused"
        logger.info(f"[AUTO-OPTIMIZE] Bot {bot.bot_name} pausado temporalmente para aplicar cambios")
    
    try:
        for key, value in changes.items():
            if key == "initial_sl_percentage":
                bot.initial_sl_percentage = Decimal(str(value))
            else:
                setattr(bot, key, value)
        
        # Reactivar el bot si estaba activo
        if was_active:
            bot.status = "active"
            logger.info(f"[AUTO-OPTIMIZE] Bot {bot.bot_name} reactivado con nuevos parámetros")
    except Exception as e:
        # Si hay error, mantener el bot pausado para revisión manual
        logger.error(f"[AUTO-OPTIMIZE] Error aplicando cambios a {bot.bot_name}: {e}")
        if was_active:
            logger.warning(f"[AUTO-OPTIMIZE] Bot {bot.bot_name} permanece pausado por error")
    
    # 11. Actualizar tracking
    now = datetime.now(timezone.utc)
    bot.auto_optimize_last_eval_at = now
    bot.auto_optimize_trades_at_eval = trade_count
    
    # También actualizar el tracking general del optimizer (para cooldown visual)
    bot.optimizer_applied_at = now
    bot.optimizer_trades_at_apply = trade_count
    bot.optimizer_applied_params = changes
    
    # Agregar al historial con tracking completo para medir efectividad
    history = bot.auto_optimize_history or []
    
    # Guardar valores ANTES de los cambios
    before_values = {}
    if "initial_sl_percentage" in changes:
        before_values["initial_sl_percentage"] = float(bot.initial_sl_percentage)
    if "leverage" in changes:
        before_values["leverage"] = bot.leverage
    if "take_profits" in changes:
        before_values["take_profits"] = bot.take_profits
    if "signal_confirmation_minutes" in changes:
        before_values["signal_confirmation_minutes"] = bot.signal_confirmation_minutes
    
    history_entry = {
        "timestamp": now.isoformat(),
        "trade_count": trade_count,
        "changes": changes,
        "before": before_values,
        "confidence": confidence["name"],
        "action_level": action_eval["name"],
        "indicators_before": {
            k: {"value": v["value"], "zone": v["zone"]} 
            for k, v in action_eval["indicators"].items()
        },
        # Campos para calcular efectividad después
        "effectiveness": None,  # Se calculará en próximas evaluaciones
        "trades_after": None,   # Trades después de aplicar
        "win_rate_after": None,
        "profit_factor_after": None,
    }
    history.append(history_entry)
    
    # Mantener solo últimos 20 registros para análisis de largo plazo
    bot.auto_optimize_history = history[-20:]
    
    await db.commit()
    
    logger.info(f"[AUTO-OPTIMIZE] Bot {bot.bot_name}: aplicados {len(changes)} cambios. "
                f"Confianza: {confidence['name']}, Nivel: {action_eval['name']}")
    
    return {
        "status": "applied",
        "message": f"Cambios aplicados con {confidence['label']}",
        "changes": changes,
        "confidence": confidence,
        "action_level": action_eval,
        "trade_count": trade_count,
        "next_eval_after": trade_count + reeval_after,
        "indicators": action_eval["indicators"],
    }



@router.get("/{bot_id}/effectiveness-dashboard")
async def get_effectiveness_dashboard(
    bot_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna el dashboard de efectividad con análisis de qué cambios funcionaron mejor.
    """
    bot_result = await db.execute(
        select(BotConfig).where(
            BotConfig.id == bot_id,
            BotConfig.user_id == user_id
        )
    )
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")
    
    history = bot.auto_optimize_history or []
    
    # Si no hay historial, retornar vacío
    if not history:
        return {
            "message": "No hay datos de auto-optimización todavía",
            "summary": None,
            "changes_by_parameter": {},
            "timeline": [],
        }
    
    # Calcular efectividad ponderada
    weighted_stats = _calculate_weighted_effectiveness(history)
    
    # Analizar efectividad por parámetro
    changes_by_param = {}
    for entry in history:
        if entry.get("effectiveness") is None:
            continue
        
        for param, value in entry.get("changes", {}).items():
            if param not in changes_by_param:
                changes_by_param[param] = {
                    "count": 0,
                    "total_effectiveness": 0,
                    "values_tried": [],
                    "best_value": None,
                    "best_effectiveness": float('-inf'),
                }
            
            # Aplicar decaimiento temporal
            timestamp = entry.get("timestamp", "")
            effectiveness = entry["effectiveness"]
            if timestamp:
                try:
                    entry_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    days_ago = (datetime.now(timezone.utc) - entry_date).days
                    effectiveness = _apply_time_decay(effectiveness, days_ago)
                except:
                    pass
            
            changes_by_param[param]["count"] += 1
            changes_by_param[param]["total_effectiveness"] += effectiveness
            changes_by_param[param]["values_tried"].append({
                "value": value,
                "effectiveness": effectiveness,
                "timestamp": timestamp,
            })
            
            # Guardar el mejor valor
            if effectiveness > changes_by_param[param]["best_effectiveness"]:
                changes_by_param[param]["best_effectiveness"] = effectiveness
                changes_by_param[param]["best_value"] = value
    
    # Calcular promedios
    for param in changes_by_param:
        count = changes_by_param[param]["count"]
        if count > 0:
            changes_by_param[param]["avg_effectiveness"] = round(
                changes_by_param[param]["total_effectiveness"] / count, 2
            )
        del changes_by_param[param]["total_effectiveness"]
    
    # Timeline de cambios
    timeline = []
    for entry in history[-20:]:  # Últimos 20 cambios
        if entry.get("changes"):
            timeline.append({
                "timestamp": entry.get("timestamp"),
                "changes": entry.get("changes"),
                "effectiveness": entry.get("effectiveness"),
                "confidence": entry.get("confidence"),
                "action_level": entry.get("action_level"),
                "trade_count": entry.get("trade_count"),
            })
    
    # Resumen ejecutivo
    summary = {
        "total_auto_changes": len([e for e in history if e.get("changes")]),
        "weighted_effectiveness": weighted_stats["weighted_avg"],
        "trend": weighted_stats["trend"],
        "most_effective_param": max(
            changes_by_param.items(),
            key=lambda x: x[1].get("avg_effectiveness", float('-inf'))
        )[0] if changes_by_param else None,
    }
    
    return {
        "summary": summary,
        "weighted_stats": weighted_stats,
        "changes_by_parameter": changes_by_param,
        "timeline": timeline,
        "config": bot.auto_optimize_config,
    }



# ═══════════════════════════════════════════════════════════════════════════
# OPTIMIZER DB - Centro de Control Global
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/db/global")
async def get_optimizer_db_global(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna datos globales de todos los bots para el Optimizer DB.
    KPIs agregados y listado completo.
    """
    # Obtener solo bots REALES - mismo criterio que /bots
    # Excluir posiciones manuales (prefijo [MANUAL])
    from sqlalchemy import not_
    bots_result = await db.execute(
        select(BotConfig)
        .where(
            BotConfig.user_id == user_id,
            not_(BotConfig.bot_name.like("[MANUAL]%")),
        )
        .order_by(BotConfig.created_at.desc())
    )
    bots = bots_result.scalars().all()
    
    if not bots:
        return {
            "kpis": {
                "total_bots": 0,
                "auto_enabled": 0,
                "global_success_rate": 0,
                "total_improvement": 0,
                "critical_bots": 0,
            },
            "bots": [],
            "alerts": [],
        }
    
    bots_data = []
    total_changes = 0
    positive_changes = 0
    total_effectiveness = 0
    critical_bots = 0
    alerts = []
    
    for bot in bots:
        # Contar trades del bot
        trades_result = await db.execute(
            select(ExchangeTrade).where(
                ExchangeTrade.bot_id == bot.id,
                ExchangeTrade.source == "bot",
                ExchangeTrade.closed_at.is_not(None),
            )
        )
        trades = trades_result.scalars().all()
        trade_count = len(trades)
        
        # Análisis básico
        analysis = None
        health = None
        if trade_count >= 3:
            trade_views = [
                _TradeView(
                    realized_pnl=t.realized_pnl,
                    entry_price=t.entry_price,
                    quantity=t.quantity,
                    side=t.side or "long",
                    opened_at=t.opened_at,
                    closed_at=t.closed_at,
                )
                for t in trades
            ]
            
            sig_result = await db.execute(
                select(SignalLog).where(
                    SignalLog.bot_id == bot.id,
                    SignalLog.signal_action.in_(["long", "short"]),
                )
            )
            signals = sig_result.scalars().all()
            
            analysis = _analyze_trades(trade_views, signals)
            health = _calculate_health_score(analysis)
        
        # Datos de auto-optimización
        history = bot.auto_optimize_history or []
        auto_changes = [h for h in history if h.get("effectiveness") is not None]
        
        bot_effectiveness = sum(h.get("effectiveness", 0) for h in auto_changes)
        bot_positive = len([h for h in auto_changes if (h.get("effectiveness") or 0) > 0])
        
        total_changes += len(auto_changes)
        positive_changes += bot_positive
        total_effectiveness += bot_effectiveness
        
        # Verificar si está en zona crítica
        is_critical = health and health["score"] < 40
        if is_critical:
            critical_bots += 1
            alerts.append({
                "type": "critical_bot",
                "bot_id": str(bot.id),
                "bot_name": bot.bot_name,
                "message": f"{bot.bot_name} tiene salud crítica ({health['score']}/100)",
            })
        
        # Alerta si no hay cambios recientes
        last_change = history[-1] if history else None
        if last_change and last_change.get("timestamp"):
            try:
                last_date = datetime.fromisoformat(last_change["timestamp"].replace("Z", "+00:00"))
                days_ago = (datetime.now(timezone.utc) - last_date).days
                if days_ago > 30 and bot.auto_optimize_enabled:
                    alerts.append({
                        "type": "stale_bot",
                        "bot_id": str(bot.id),
                        "bot_name": bot.bot_name,
                        "message": f"{bot.bot_name} sin cambios en {days_ago} días",
                    })
            except:
                pass
        
        bots_data.append({
            "id": str(bot.id),
            "name": bot.bot_name,
            "symbol": bot.symbol,
            "timeframe": bot.timeframe,
            "status": bot.status,
            "auto_enabled": bot.auto_optimize_enabled,
            "trade_count": trade_count,
            "win_rate": analysis.get("win_rate") if analysis else None,
            "profit_factor": analysis.get("profit_factor") if analysis else None,
            "health_score": health["score"] if health else None,
            "health_level": health["level"] if health else None,
            "effectiveness": bot_effectiveness,
            "total_changes": len(auto_changes),
            "positive_changes": bot_positive,
            "success_rate": round((bot_positive / len(auto_changes)) * 100, 1) if auto_changes else 0,
            "last_change": last_change.get("timestamp") if last_change else None,
            "last_change_summary": last_change.get("changes") if last_change else None,
            "config": bot.auto_optimize_config,
        })
    
    # Ordenar bots: primero los críticos, luego por salud
    bots_data.sort(key=lambda b: (b.get("health_score") or 100))
    
    # Calcular KPIs globales
    global_success_rate = round((positive_changes / total_changes) * 100, 1) if total_changes else 0
    
    return {
        "kpis": {
            "total_bots": len(bots),
            "auto_enabled": len([b for b in bots if b.auto_optimize_enabled]),
            "global_success_rate": global_success_rate,
            "total_improvement": round(total_effectiveness, 2),
            "critical_bots": critical_bots,
            "total_changes": total_changes,
        },
        "bots": bots_data,
        "alerts": alerts,
    }
