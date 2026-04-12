"""
Optimizador de parámetros por bot.

Analiza el histórico de posiciones cerradas y señales de un bot y propone:
- Stop loss inicial óptimo
- Take profits escalonados
- Apalancamiento recomendado
- Minutos de confirmación de señal
"""
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id
from app.models.bot_config import BotConfig
from app.models.position import Position
from app.models.signal_log import SignalLog
from app.services.database import get_db

router = APIRouter(prefix="/optimizer", tags=["optimizer"])

MIN_TRADES = 5  # Mínimo de trades para sugerencias fiables


@router.get("/{bot_id}")
async def get_optimizer(
    bot_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Analiza el histórico de posiciones cerradas del bot y devuelve
    métricas + sugerencias de parámetros optimizados.
    """
    # Cargar bot
    bot_result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user_id)
    )
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot no encontrado")

    # Posiciones cerradas con PnL
    pos_result = await db.execute(
        select(Position).where(
            Position.bot_id == bot_id,
            Position.status == "closed",
            Position.realized_pnl.is_not(None),
        ).order_by(Position.closed_at)
    )
    positions = pos_result.scalars().all()

    # Señales (long/short) del bot
    sig_result = await db.execute(
        select(SignalLog).where(
            SignalLog.bot_id == bot_id,
            SignalLog.signal_action.in_(["long", "short"]),
        )
    )
    signals = sig_result.scalars().all()

    analysis = _analyze(positions, signals)
    suggestions = _suggest(bot, analysis)

    return {
        "bot_id": str(bot_id),
        "bot_name": bot.bot_name,
        "symbol": bot.symbol,
        "timeframe": bot.timeframe,
        "insufficient_data": len(positions) < MIN_TRADES,
        "analysis": analysis,
        "current": {
            "signal_confirmation_minutes": bot.signal_confirmation_minutes,
            "initial_sl_percentage": float(bot.initial_sl_percentage),
            "take_profits": bot.take_profits,
            "leverage": bot.leverage,
        },
        "suggestions": suggestions,
    }


# ─── Motor de análisis ────────────────────────────────────────

def _analyze(positions: list, signals: list) -> dict:
    if not positions:
        return _empty_analysis()

    pnls = [p.realized_pnl for p in positions if p.realized_pnl is not None]
    total = len(pnls)
    if total == 0:
        return _empty_analysis()

    winners = [p for p in positions if p.realized_pnl and p.realized_pnl > 0]
    losers  = [p for p in positions if p.realized_pnl and p.realized_pnl <= 0]
    n_win   = len(winners)
    n_loss  = len(losers)
    win_rate = round(n_win / total, 4)

    avg_win  = float(sum(p.realized_pnl for p in winners) / n_win)  if n_win  else 0.0
    avg_loss = float(sum(p.realized_pnl for p in losers)  / n_loss) if n_loss else 0.0

    total_win  = float(sum(p.realized_pnl for p in winners)) if winners else 0.0
    total_loss = abs(float(sum(p.realized_pnl for p in losers))) if losers else 0.0
    profit_factor = round(total_win / total_loss, 2) if total_loss > 0 else None

    # Duración de operaciones
    def _hours(pos):
        if pos.opened_at and pos.closed_at:
            return (pos.closed_at - pos.opened_at).total_seconds() / 3600
        return None

    win_durations  = [h for p in winners if (h := _hours(p)) is not None]
    loss_durations = [h for p in losers  if (h := _hours(p)) is not None]
    all_durations  = win_durations + loss_durations

    avg_duration      = round(sum(all_durations)  / len(all_durations),  1) if all_durations  else 0.0
    avg_winner_hours  = round(sum(win_durations)  / len(win_durations),  1) if win_durations  else 0.0
    avg_loser_hours   = round(sum(loss_durations) / len(loss_durations), 1) if loss_durations else 0.0

    # SL: distancia % entre entrada y SL
    sl_pcts  = []
    sl_hits  = 0
    for p in positions:
        if p.entry_price and p.current_sl_price and float(p.entry_price) > 0:
            pct = abs(float(p.entry_price) - float(p.current_sl_price)) / float(p.entry_price) * 100
            sl_pcts.append(pct)

            # Detectar cierre por SL: pérdida real ≈ pérdida esperada en SL (±15%)
            if p.realized_pnl and float(p.realized_pnl) < 0:
                expected = (float(p.current_sl_price) - float(p.entry_price)) * float(p.quantity)
                if p.side == "short":
                    expected = -expected
                denom = max(abs(expected), 0.01)
                if abs(float(p.realized_pnl) - expected) / denom < 0.15:
                    sl_hits += 1

    avg_sl_pct   = round(sum(sl_pcts) / len(sl_pcts), 2) if sl_pcts else 0.0
    sl_hit_rate  = round(sl_hits / n_loss, 4) if n_loss > 0 else 0.0

    # Profit/loss % sobre el nominal (sin leverage)
    win_pcts = []
    for p in winners:
        entry = float(p.entry_price or 0)
        qty   = float(p.quantity or 0)
        if entry > 0 and qty > 0:
            win_pcts.append(float(p.realized_pnl) / (entry * qty) * 100)

    loss_pcts = []
    for p in losers:
        entry = float(p.entry_price or 0)
        qty   = float(p.quantity or 0)
        if entry > 0 and qty > 0:
            loss_pcts.append(abs(float(p.realized_pnl)) / (entry * qty) * 100)

    avg_win_pct  = round(sum(win_pcts)  / len(win_pcts),  2) if win_pcts  else 0.0
    avg_loss_pct = round(sum(loss_pcts) / len(loss_pcts), 2) if loss_pcts else 0.0

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
        "total_closed":       total,
        "winning":            n_win,
        "losing":             n_loss,
        "win_rate":           win_rate,
        "profit_factor":      profit_factor,
        "avg_win_pnl":        round(avg_win,  2),
        "avg_loss_pnl":       round(avg_loss, 2),
        "avg_win_pct":        avg_win_pct,
        "avg_loss_pct":       avg_loss_pct,
        "avg_duration_hours": avg_duration,
        "avg_winner_hours":   avg_winner_hours,
        "avg_loser_hours":    avg_loser_hours,
        "sl_hit_count":       sl_hits,
        "sl_hit_rate":        sl_hit_rate,
        "avg_sl_pct":         avg_sl_pct,
        "signals_total":      total_signals,
        "signals_cancelled":  cancelled,
        "signals_cancel_rate": cancel_rate,
    }


def _empty_analysis() -> dict:
    return {
        "total_closed": 0, "winning": 0, "losing": 0, "win_rate": 0.0,
        "profit_factor": None, "avg_win_pnl": 0.0, "avg_loss_pnl": 0.0,
        "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
        "avg_duration_hours": 0.0, "avg_winner_hours": 0.0, "avg_loser_hours": 0.0,
        "sl_hit_count": 0, "sl_hit_rate": 0.0, "avg_sl_pct": 0.0,
        "signals_total": 0, "signals_cancelled": 0, "signals_cancel_rate": 0.0,
    }


# ─── Motor de sugerencias ─────────────────────────────────────

def _suggest(bot: BotConfig, a: dict) -> dict:
    if a["total_closed"] == 0:
        return {}

    win_rate      = a["win_rate"]
    profit_factor = a["profit_factor"] or 1.0
    avg_sl_pct    = a["avg_sl_pct"]
    sl_hit_rate   = a["sl_hit_rate"]
    avg_win_pct   = a["avg_win_pct"]
    avg_loss_pct  = a["avg_loss_pct"]
    cancel_rate   = a["signals_cancel_rate"]

    current_sl   = float(bot.initial_sl_percentage)
    current_conf = bot.signal_confirmation_minutes or 0
    current_lev  = bot.leverage

    suggestions: dict = {}

    # ── Stop Loss ──────────────────────────────────────────────
    if avg_sl_pct > 0:
        if sl_hit_rate > 0.5 and win_rate < 0.5:
            new_sl = round(avg_sl_pct * 1.25, 2)
            reason = (
                f"El {int(sl_hit_rate*100)}% de las pérdidas tocaron el SL — "
                "podría ser demasiado ajustado. Ampliarlo un 25% puede evitar salidas prematuras."
            )
        elif win_rate > 0.65 and sl_hit_rate < 0.2:
            new_sl = round(max(0.3, avg_sl_pct * 0.9), 2)
            reason = (
                f"Win rate {int(win_rate*100)}% con pocas salidas por SL ({int(sl_hit_rate*100)}%). "
                "Puedes ajustar levemente el SL para mejorar el ratio riesgo/beneficio."
            )
        else:
            new_sl = round(avg_sl_pct, 2) if avg_sl_pct > 0 else current_sl
            reason = (
                f"La distancia media real al SL fue {avg_sl_pct:.1f}%. "
                "Alinear el SL con el comportamiento histórico real del activo."
            )
        suggestions["initial_sl_percentage"] = {
            "value": max(0.1, new_sl),
            "reason": reason,
        }

    # ── Take Profits ───────────────────────────────────────────
    if avg_win_pct > 0.2:
        # Niveles escalonados en 40 / 75 / 120 % del profit medio de ganadores
        tp1 = max(0.2, round(avg_win_pct * 0.40, 1))
        tp2 = max(0.4, round(avg_win_pct * 0.75, 1))
        tp3 = max(0.8, round(avg_win_pct * 1.20, 1))

        tp_value = [
            {"profit_percent": tp1, "close_percent": 30.0},
            {"profit_percent": tp2, "close_percent": 40.0},
        ]
        if tp3 > tp2 + 0.3:
            tp_value.append({"profit_percent": tp3, "close_percent": 30.0})

        suggestions["take_profits"] = {
            "value": tp_value,
            "reason": (
                f"Media de ganancia en trades ganadores: {avg_win_pct:.1f}%. "
                f"TPs en {tp1:.1f}% (30%), {tp2:.1f}% (40%) y {tp3:.1f}% (30%) del nominal."
            ),
        }

    # ── Apalancamiento ─────────────────────────────────────────
    if avg_loss_pct > 0:
        wl_ratio = avg_win_pct / avg_loss_pct if avg_loss_pct > 0 else 1.0
        # Criterio Kelly simplificado
        kelly = win_rate - (1 - win_rate) / wl_ratio if wl_ratio > 0 else -1

        if kelly <= 0 or (win_rate < 0.4 and profit_factor < 1.2):
            new_lev = max(1, current_lev - 2)
            reason = (
                f"Win rate {int(win_rate*100)}% y ratio G/P {wl_ratio:.1f}x indican "
                "riesgo elevado. Reducir el apalancamiento protege el capital."
            )
        elif win_rate >= 0.60 and profit_factor >= 1.8:
            new_lev = min(20, current_lev + 2)
            reason = (
                f"Win rate {int(win_rate*100)}% con profit factor {profit_factor:.1f}x. "
                "El histórico soporta incrementar ligeramente el apalancamiento."
            )
        else:
            new_lev = current_lev
            reason = (
                f"Win rate {int(win_rate*100)}% y profit factor {profit_factor:.1f}x. "
                "El apalancamiento actual es coherente con el rendimiento histórico."
            )
        suggestions["leverage"] = {
            "value": new_lev,
            "reason": reason,
        }

    # ── Confirmación de señal ──────────────────────────────────
    if win_rate < 0.45 and current_conf == 0:
        new_conf = 2
        reason = (
            f"Win rate del {int(win_rate*100)}% es bajo con confirmación en 0 min. "
            "Un delay de 2 min puede filtrar señales que revierten rápido."
        )
    elif win_rate < 0.45 and current_conf > 0:
        new_conf = min(current_conf + 1, 5)
        reason = (
            f"Win rate bajo ({int(win_rate*100)}%) incluso con delay activo. "
            f"Aumentar a {new_conf} min podría mejorar la calidad de entradas."
        )
    elif cancel_rate > 0.25:
        new_conf = max(1, current_conf)
        reason = (
            f"El filtro anti-falso canceló el {int(cancel_rate*100)}% de señales — "
            "está funcionando. Mantener o aumentar para seguir filtrando."
        )
    elif win_rate >= 0.60 and current_conf > 2:
        new_conf = max(0, current_conf - 1)
        reason = (
            f"Win rate del {int(win_rate*100)}% es bueno. "
            "Podrías reducir el delay para capturar más entradas sin perder calidad."
        )
    else:
        new_conf = current_conf
        reason = "El delay actual es coherente con el rendimiento histórico del bot."

    suggestions["signal_confirmation_minutes"] = {
        "value": new_conf,
        "reason": reason,
    }

    return suggestions
