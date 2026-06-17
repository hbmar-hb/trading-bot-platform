"""Context-Aware Threshold Registry (CATR).

Umbrales de score y probabilidad por (ticker, timeframe, regime).
Aprende online con cada trade resuelto. Persiste en Redis con TTL 30 días.

Integración:
  - Lectura: bot_activator.py (antes de filtrar por score)
  - Escritura: ai_outcome_tracker.py (tras resolver señal)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np
from loguru import logger

from app.services.cache import sync_redis


class ContextThresholdRegistry:
    """Mantiene thresholds adaptativos por contexto de mercado."""

    REDIS_KEY_PREFIX = "catr"
    TTL_SECONDS = 30 * 86400  # 30 días
    MIN_SAMPLES = 15
    WINDOW_SIZE = 50

    GLOBAL_FALLBACK = {
        "score_threshold": 55,
        "prob_threshold": 0.55,
        "confidence": 0.0,
        "reason": "global_fallback",
    }

    def __init__(self):
        self.redis = sync_redis

    def _key(self, ticker: str, timeframe: str, regime: str) -> str:
        return f"{self.REDIS_KEY_PREFIX}:{ticker.upper()}:{timeframe}:{regime}"

    def get(self, ticker: str, timeframe: str, regime: str) -> dict[str, Any]:
        """Retorna thresholds adaptados al contexto.

        Si no hay datos suficientes (< MIN_SAMPLES), retorna GLOBAL_FALLBACK
        con confidence=0 para que el llamador use thresholds globales.
        """
        key = self._key(ticker, timeframe, regime)
        data = self.redis.get(key)

        if not data:
            return {**self.GLOBAL_FALLBACK, "context": key, "reason": "no_data"}

        try:
            reg = json.loads(data)
        except json.JSONDecodeError:
            logger.warning(f"[CATR] Corrupt data for {key}, resetting")
            self.redis.delete(key)
            return {**self.GLOBAL_FALLBACK, "context": key, "reason": "corrupt_data"}

        n_trades = reg.get("n_trades", 0)
        if n_trades < self.MIN_SAMPLES:
            # Recovery / exploration mode: when data is scarce, LOWER thresholds
            # so the system can accumulate ground-truth data instead of choking.
            return {
                "score_threshold": 50,
                "prob_threshold": 0.50,
                "confidence": 0.0,
                "reason": "exploration_mode",
                "context": key,
                "partial_n_trades": n_trades,
            }

        winrate_window = reg.get("winrate_window", [])
        recent_wr = (
            float(np.mean(winrate_window[-self.WINDOW_SIZE:]))
            if winrate_window
            else 0.0
        )

        gross_profits = reg.get("gross_profits", [])
        gross_losses = reg.get("gross_losses", [])
        recent_pf = self._compute_pf(gross_profits, gross_losses)

        score_th = reg.get(
            "score_threshold", self.GLOBAL_FALLBACK["score_threshold"]
        )
        prob_th = reg.get(
            "prob_threshold", self.GLOBAL_FALLBACK["prob_threshold"]
        )

        # ── Ajuste dinámico basado en rendimiento reciente ──
        if recent_wr > 0.62 and recent_pf > 1.3:
            # Zona verde: más selectivos solo si tenemos datos sólidos
            if n_trades >= 50:
                score_th = min(88, score_th + 0.3)
                prob_th = min(0.82, prob_th + 0.005)
        elif recent_wr < 0.42 or recent_pf < 0.9:
            # Zona roja: con pocos trades NO subir umbrales (necesitamos datos).
            # Con muchos datos, subir selectividad moderadamente.
            if n_trades >= 50:
                score_th = min(85, score_th + 0.8)
                prob_th = min(0.80, prob_th + 0.01)
            else:
                # Recovery mode: bajar para acumular muestras
                score_th = max(50, score_th - 1.5)
                prob_th = max(0.50, prob_th - 0.02)
        elif recent_wr < 0.50:
            # Zona amarilla: exploración controlada
            score_th = max(55, score_th - 0.5)
            prob_th = max(0.55, prob_th - 0.01)

        confidence = min(1.0, n_trades / 100)

        return {
            "score_threshold": round(score_th, 1),
            "prob_threshold": round(prob_th, 3),
            "confidence": round(confidence, 2),
            "recent_winrate": round(recent_wr, 3),
            "recent_pf": round(recent_pf, 2),
            "n_trades": n_trades,
            "reason": "context_optimized",
            "context": key,
        }

    def update(
        self,
        ticker: str,
        timeframe: str,
        regime: str,
        outcome: dict,
    ) -> None:
        """Actualiza estadísticas tras un trade resuelto.

        Args:
            outcome: dict con al menos 'pnl_pct'. Opcionalmente:
                     'signal_score', 'signal_prob', 'label'.
        """
        key = self._key(ticker, timeframe, regime)

        # Leer actual
        data = self.redis.get(key)
        if data:
            try:
                reg = json.loads(data)
            except json.JSONDecodeError:
                reg = self._init_registry()
        else:
            reg = self._init_registry()

        reg["n_trades"] = reg.get("n_trades", 0) + 1

        pnl = outcome.get("pnl_pct", 0.0)
        win = 1 if pnl > 0 else 0

        # Winrate móvil
        reg.setdefault("winrate_window", []).append(win)
        if len(reg["winrate_window"]) > self.WINDOW_SIZE:
            reg["winrate_window"].pop(0)

        # Profit factor móvil (dos ventanas separadas para cálculo real)
        if pnl > 0:
            reg.setdefault("gross_profits", []).append(float(pnl))
            if len(reg["gross_profits"]) > self.WINDOW_SIZE:
                reg["gross_profits"].pop(0)
        else:
            reg.setdefault("gross_losses", []).append(float(abs(pnl)))
            if len(reg["gross_losses"]) > self.WINDOW_SIZE:
                reg["gross_losses"].pop(0)

        # Historial compacto para debugging / trazabilidad
        reg.setdefault("pnl_history", []).append(
            {
                "pnl": round(float(pnl), 4),
                "score": outcome.get("signal_score"),
                "prob": outcome.get("signal_prob"),
                "label": outcome.get("label"),
                "timestamp": datetime.now().isoformat(),
            }
        )
        if len(reg["pnl_history"]) > 200:
            reg["pnl_history"].pop(0)

        # Guardar con TTL (atómico respecto a otras conexiones Redis)
        self.redis.setex(key, self.TTL_SECONDS, json.dumps(reg))

    def _init_registry(self) -> dict:
        return {
            "score_threshold": self.GLOBAL_FALLBACK["score_threshold"],
            "prob_threshold": self.GLOBAL_FALLBACK["prob_threshold"],
            "n_trades": 0,
            "winrate_window": [],
            "gross_profits": [],
            "gross_losses": [],
            "pnl_history": [],
        }

    @staticmethod
    def _compute_pf(profits: list[float], losses: list[float]) -> float:
        gp = sum(profits) if profits else 0.0
        gl = sum(losses) if losses else 0.0
        if gl == 0:
            return 999.0 if gp > 0 else 0.0
        return gp / gl


# ═══════════════════════════════════════════════════════════
# Helper de integración (uso desde tasks Celery)
# ═══════════════════════════════════════════════════════════

def update_catr_from_signal(signal, outcome_label: str, pnl_pct: float | None) -> None:
    """Actualiza CATR usando una señal AI resuelta.

    Esta función es sync y puede llamarse desde tasks Celery o
    desde coroutines (operación Redis rápida, <1ms).
    """
    try:
        if not signal or pnl_pct is None:
            return

        features = signal.features or {}
        regime = features.get("market_regime", "unknown")

        catr = ContextThresholdRegistry()
        catr.update(
            ticker=signal.ticker,
            timeframe=signal.timeframe,
            regime=regime,
            outcome={
                "pnl_pct": pnl_pct,
                "signal_score": signal.score,
                "signal_prob": getattr(signal, "success_probability", None),
                "label": outcome_label,
            },
        )
        logger.debug(
            f"[CATR] Updated {signal.ticker}/{signal.timeframe}/{regime} "
            f"with {outcome_label} pnl={pnl_pct:.3f}"
        )
    except Exception as exc:
        logger.debug(f"[CATR] Update failed (non-critical): {exc}")
