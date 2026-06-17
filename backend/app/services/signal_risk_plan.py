"""Signal-Aware Position Plan (SAPP).

Genera un plan de posición único por señal AI, combinando:
  - Sizing base por calidad de señal (complementa Kelly)
  - TP escalonado por calidad de señal
  - SL dinámico por calidad y régimen de mercado
  - Time limit adaptativo
  - Emergency brake por calidad

Integración:
  - engine.py genera el plan y lo guarda en Position.extra_config["dynamic_plan"]
  - TrailingWorker lee el plan y ejecuta TP/SL dinámicos
  - Fallback a legacy (BotConfig) si no hay plan
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Dict, Optional

from loguru import logger


@dataclass
class TPLevel:
    level: int
    close_pct: float       # % de posición a cerrar en este nivel
    r_multiple: float      # distancia en múltiplos de R desde entrada
    action_after_hit: str  # "breakeven" | "trailing" | "hold"
    price: float | None = None  # precio absoluto estructural (si viene de forward_levels)


@dataclass
class PositionPlan:
    size_usd: float
    sl_distance: float     # en % del precio (o ATR múltiplo)
    sl_price: float | None
    tp_levels: List[TPLevel]
    time_limit_bars: int
    execution_mode: str    # "aggressive" | "standard" | "conservative"
    emergency_brake_at_r: float
    scale_out_config: Optional[Dict] = None
    quality_tier: str = "MODERATE"
    score: float = 0.0
    prob: float = 0.0


class SignalRiskPlanner:
    """Genera plan de posición único por señal AI.

    No reemplaza Kelly sizing ni el exchange.calculate_quantity —
    genera metaparámetros (TP structure, SL distance, time limit)
    que engine.py y TrailingWorker consumen.
    """

    # Timeframe → base time limit (barras)
    _TIME_LIMIT_BASE = {
        "1m": 20, "5m": 30, "15m": 50, "30m": 40,
        "1h": 24, "2h": 18, "4h": 12, "6h": 10,
        "8h": 8, "12h": 6, "1d": 6, "3d": 4, "1w": 3,
    }

    def generate_plan(
        self,
        signal,
        account_equity: float,
        market_context: dict | None = None,
        forward_levels: list[dict] | None = None,
    ) -> PositionPlan:
        """Genera plan completo de posición para una señal AI.

        Args:
            signal: objeto AISignal (o cualquier objeto con quality_tier, score, etc.)
            account_equity: equity total de la cuenta en USDT
            market_context: dict opcional con "regime", "atr_14", etc.
            forward_levels: niveles estructurales ICT+SMC desde bot_activator
        """
        quality = getattr(signal, "quality_tier", "MODERATE") or "MODERATE"
        score = getattr(signal, "score", 0) or 0
        prob = getattr(signal, "success_probability", None) or 0.5
        timeframe = getattr(signal, "timeframe", "1h") or "1h"

        regime = (market_context or {}).get("regime", "unknown")
        atr = (market_context or {}).get("atr_14", 0)

        # 1. Sizing base por calidad (% del equity)
        base_size = self._base_size_by_quality(quality, account_equity)

        # 2. Multiplicador por score dentro del tier
        quality_mult = self._quality_multiplier(quality, score)
        size = base_size * quality_mult

        # 3. Estructura TP escalonado
        # Pass entry/sl from signal so structural levels can be converted to R-multiples
        entry_price = float(getattr(signal, "entry_price", 0) or 0)
        sl_price = float(getattr(signal, "stop_loss", 0) or 0)
        direction = getattr(signal, "direction", "long") or "long"
        tp_levels = self._build_tp_structure(
            quality, score, prob, regime, forward_levels, entry_price, sl_price, direction
        )

        # Fase B: if the signal carries a confluence-aware dynamic TP plan,
        # override the generic SAPP structure with the signal's own levels.
        signal_tp_levels = (getattr(signal, "features", None) or {}).get("tp_levels")
        if signal_tp_levels:
            dynamic_tps: List[TPLevel] = []
            for lvl in signal_tp_levels:
                dynamic_tps.append(TPLevel(
                    level=int(lvl.get("level", len(dynamic_tps) + 1)),
                    close_percent=float(lvl.get("close_percent", 0.33)),
                    r_multiple=float(lvl.get("r_multiple", 1.0)),
                    action_after_hit="breakeven" if len(dynamic_tps) == 0 else "trailing",
                    price=float(lvl.get("price", 0)) or None,
                ))
            if dynamic_tps:
                tp_levels = dynamic_tps

        # 4. SL dinámico (distancia desde entrada)
        sl_mult = self._sl_multiplier(score, prob, regime)
        sl_distance = atr * sl_mult if atr > 0 else 0.015

        # 5. Time limit adaptativo
        time_limit = self._time_limit(score, regime, timeframe)

        # 6. Emergency brake por calidad
        emergency_r = self._emergency_brake_r(quality)

        return PositionPlan(
            size_usd=round(size, 2),
            sl_distance=round(sl_distance, 6),
            sl_price=None,  # engine.py calcula tras fill
            tp_levels=tp_levels,
            time_limit_bars=time_limit,
            execution_mode="aggressive" if score > 85 else "standard",
            emergency_brake_at_r=emergency_r,
            scale_out_config={
                "enabled": len(tp_levels) > 1,
                "levels": [
                    {"r": tp.r_multiple, "close_pct": tp.close_pct, "price": tp.price}
                    for tp in tp_levels
                ],
            },
            quality_tier=quality,
            score=score,
            prob=prob,
        )

    # ── Internal helpers ──────────────────────────────────────────

    def _base_size_by_quality(self, quality: str, equity: float) -> float:
        mult = {
            "STRONG": 0.02,    # 2% equity
            "MODERATE": 0.01,  # 1% equity
            "WEAK": 0.005,     # 0.5% equity
        }.get(quality, 0.01)
        return equity * mult

    def _quality_multiplier(self, quality: str, score: float) -> float:
        mult = {
            "STRONG": 1.0,
            "MODERATE": 0.7,
            "WEAK": 0.4,
        }.get(quality, 0.7)

        if score >= 88:
            mult *= 1.15
        elif score < 70:
            mult *= 0.85

        return mult

    def _build_tp_structure(
        self,
        quality: str,
        score: float,
        prob: float,
        regime: str,
        forward_levels: list[dict] | None = None,
        entry_price: float = 0.0,
        sl_price: float = 0.0,
        direction: str = "long",
    ) -> List[TPLevel]:
        """TP escalonado por calidad de señal + contexto.

        If forward_levels are provided (ICT+SMC structural levels), use them
        directly as TP prices. Compute R-multiples for compatibility with
        trailing worker, but the actual execution price comes from structure.
        """
        # ── Structural path: use forward_levels directly ────────────────────
        if forward_levels and entry_price > 0 and sl_price > 0:
            risk = abs(entry_price - sl_price)
            if risk > 0:
                valid_levels: list[dict] = []
                is_long = direction == "long"

                for lvl in forward_levels:
                    price = float(lvl.get("price", 0))
                    kind = lvl.get("kind", "unknown")
                    if price <= 0:
                        continue
                    # Skip levels that are on the wrong side of entry
                    # For LONG: TP must be ABOVE entry
                    # For SHORT: TP must be BELOW entry
                    if is_long and price <= entry_price:
                        continue
                    if not is_long and price >= entry_price:
                        continue
                    dist = abs(price - entry_price)
                    r_mult = round(dist / risk, 3)
                    valid_levels.append({
                        "price": price,
                        "kind": kind,
                        "r_multiple": r_mult,
                        "distance": dist,
                    })

                if valid_levels:
                    # Sort by distance ASC (closest first)
                    valid_levels.sort(key=lambda x: x["distance"])

                    # Determine split based on quality
                    if quality == "STRONG" and score >= 85 and prob >= 0.75:
                        close_pcts = [0.30, 0.40, 0.30]
                        actions = ["breakeven", "trailing", "trailing"]
                    elif quality == "STRONG":
                        close_pcts = [0.50, 0.50]
                        actions = ["breakeven", "trailing"]
                    elif quality == "MODERATE" and score >= 78:
                        close_pcts = [0.60, 0.40]
                        actions = ["breakeven", "trailing"]
                    else:
                        # MODERATE/WEAK with structural levels: still split
                        # but more conservative (take more at first target)
                        close_pcts = [0.65, 0.35]
                        actions = ["breakeven", "trailing"]

                    tps: List[TPLevel] = []
                    for i, lvl in enumerate(valid_levels[:len(close_pcts)]):
                        tps.append(TPLevel(
                            level=i + 1,
                            close_pct=close_pcts[i],
                            r_multiple=lvl["r_multiple"],
                            action_after_hit=actions[i],
                            price=lvl["price"],
                        ))
                    logger.info(
                        f"[SAPP] Structural TP structure built from {len(tps)} forward levels: "
                        f"{[(tp.price, tp.r_multiple) for tp in tps]}"
                    )
                    return tps

        # ── Fallback path: generic R-multiple TPs ───────────────────────────
        if quality == "STRONG" and score >= 85 and prob >= 0.75:
            return [
                TPLevel(1, 0.30, 1.5, "breakeven"),
                TPLevel(2, 0.40, 2.5, "trailing"),
                TPLevel(3, 0.30, 4.0, "trailing"),
            ]
        elif quality == "STRONG":
            return [
                TPLevel(1, 0.50, 1.5, "breakeven"),
                TPLevel(2, 0.50, 2.5, "trailing"),
            ]
        elif quality == "MODERATE" and score >= 78:
            return [
                TPLevel(1, 0.60, 1.3, "breakeven"),
                TPLevel(2, 0.40, 2.0, "trailing"),
            ]
        else:
            return [
                TPLevel(1, 1.0, 1.5, "breakeven"),
            ]

    def _sl_multiplier(self, score: float, prob: float, regime: str) -> float:
        """Multiplicador de SL base. >1 = más ancho, <1 = más ajustado."""
        base = 1.0
        if score > 82:
            base *= 0.85
        elif score < 65:
            base *= 1.25
        if prob < 0.60:
            base *= 1.15
        if regime == "volatile":
            base *= 1.20
        elif regime == "ranging":
            base *= 0.90
        return base

    def _time_limit(self, score: float, regime: str, timeframe: str) -> int:
        base = self._TIME_LIMIT_BASE.get(timeframe, 50)
        if regime == "ranging":
            base = int(base * 0.6)
        elif score > 85:
            base = int(base * 1.4)
        return base

    def _emergency_brake_r(self, quality: str) -> float:
        """R-múltiplo donde activar EmergencyBrake (reducción 70-80%)."""
        if quality == "STRONG":
            return -1.5
        elif quality == "MODERATE":
            return -1.0
        else:
            return -0.5


# ── Helpers para conversión de precios ──────────────────────────

def calculate_tp_prices(
    entry_price: Decimal,
    side: str,
    sl_price: Decimal,
    tp_levels: List[TPLevel],
) -> List[dict]:
    """Convierte TP levels a precios absolutos.

    If the TPLevel has a structural `price` set (from forward_levels),
    use it directly. Otherwise compute from R-multiple.

    Args:
        entry_price: precio de entrada
        side: "long" | "short"
        sl_price: precio del stop loss
        tp_levels: lista de TPLevel del plan SAPP

    Returns:
        Lista de dicts con keys: level, price, close_percent, hit
    """
    risk_distance = abs(entry_price - sl_price)
    if risk_distance <= 0:
        logger.warning("[SAPP] risk_distance is 0, cannot compute TP prices")
        return []

    records = []
    for tp in tp_levels:
        # CRITICAL FIX: if structural price is available, use it directly
        if tp.price is not None and tp.price > 0:
            price = Decimal(str(tp.price))
            logger.info(
                f"[SAPP] Using structural price for TP{tp.level}: {tp.price} "
                f"(kind={getattr(tp, '_kind', 'unknown')}, r={tp.r_multiple})"
            )
        else:
            distance = risk_distance * Decimal(str(tp.r_multiple))
            if side == "long":
                price = entry_price + distance
            else:
                price = entry_price - distance

        records.append({
            "level": tp.level,
            "price": float(price),
            "close_percent": tp.close_pct,
            "hit": False,
            "action_after_hit": tp.action_after_hit,
            "r_multiple": tp.r_multiple,
        })

    return records
