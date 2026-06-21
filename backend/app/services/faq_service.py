"""Mechanical FAQ service — answers from documentation without an LLM.

When the language model is unavailable (or when the user explicitly wants a
no-LLM answer), this service routes the question to the relevant knowledge
sources and returns the matching documentation chunks verbatim.
"""
from __future__ import annotations

from app.services.knowledge_service import search_knowledge

# Keywords used to detect the topic/intent of a question. The first match wins.
_TOPIC_KEYWORDS: dict[str, set[str]] = {
    "bots": {
        "bot", "bots", "crear bot", "nuevo bot", "pausar", "deshabilitar",
        "configurar bot", "editar bot", "borrar bot", "eliminar bot",
        "modo paper", "paper trading", "capital", "apalancamiento", "sl", "tp",
        "stop loss", "take profit", "timeframe", "símbolo", "activar bot",
        "circuit breaker", "optimizer", "optimizar",
    },
    "exchanges": {
        "exchange", "exchanges", "bitunix", "bingx", "api key", "apikey",
        "conectar exchange", "cuenta", "balance", "equity", "retirar",
        "depositar", "vincular", "desvincular",
    },
    "tradingview": {
        "tradingview", "trading view", "webhook", "webhooks", "alerta",
        "alertas", "pine", "pine script", "json", "bot_id", "secret",
        "señal tradingview",
    },
    "positions": {
        "posición", "posiciones", "position", "positions", "cerrar", "cerrar posición",
        "operación", "operaciones", "trade", "trades", "pnl",
    },
    "analytics": {
        "analytics", "análisis", "métricas", "estadísticas", "rendimiento",
        "profit factor", "sharpe", "drawdown", "win rate", "historial",
        "dashboard", "gráfica", "gráfico",
    },
    "docs": {
        "docs", "documentación", "manual", "ayuda", "guía", "guia",
        "páginas habilitadas", "scope", "fase 1",
    },
    "settings": {
        "ajustes", "settings", "configuración", "configuracion", "perfil",
        "cambiar contraseña", "notificaciones", "tema", "dark mode",
    },
    "smc_ict": {
        "smc", "ict", "smart money", "inner circle", "order block", "orderblock",
        "fair value gap", "fvg", "choch", "change of character", "liquidity",
        "mitigation", "breaker", "imbalance", "kill zone", "killzone",
        "premium", "discount", "psicología", "trading en la zona",
    },
    "indicators": {
        "indicador", "indicadores", "scanner", "señal", "señales", "signal",
        "score", "tier", "probabilidad", "anti-fake", "antifake", "modelo",
        "ensemble", "features",
    },
    "market": {
        "mercado", "bitcoin", "btc", "ethereum", "eth", "nota", "notas",
        "macro", "evento", "eventos", "calendario", "fundamental",
    },
}

# Map each detected topic to the source files that should be searched.
# Order matters: earlier sources are preferred when multiple are allowed.
_TOPIC_SOURCES: dict[str, list[str]] = {
    "bots": ["phase1_user_guide.md", "platform_guide.md"],
    "exchanges": ["phase1_user_guide.md", "platform_guide.md"],
    "tradingview": ["tradingview_integration.md", "phase1_user_guide.md"],
    "positions": ["phase1_user_guide.md", "platform_guide.md"],
    "analytics": ["phase1_user_guide.md", "platform_guide.md"],
    "docs": ["phase1_user_guide.md"],
    "settings": ["phase1_user_guide.md"],
    "smc_ict": ["QUANTUM_BASE_CONOCIMIENTO_SMC_ICT.md", "ict_smc_definitions.md"],
    "indicators": ["internal_indicators.md", "QUANTUM_BASE_CONOCIMIENTO_SMC_ICT.md"],
    "market": ["market_notes.md"],
}

# Fallback order when no specific topic is detected.
_DEFAULT_SOURCES: list[str] = [
    "phase1_user_guide.md",
    "platform_guide.md",
    "tradingview_integration.md",
]


def detect_topic(query: str) -> str | None:
    """Return the best matching topic for a user question, if any."""
    lowered = query.lower()
    for topic, keywords in _TOPIC_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return topic
    return None


def answer_faq(
    query: str,
    allowed_sources: list[str] | None = None,
    top_k: int = 5,
) -> str:
    """Return a mechanical FAQ answer from the knowledge base.

    Args:
        query: user question.
        allowed_sources: optional whitelist of source filenames. If provided,
            topic detection is skipped and only those sources are searched.
        top_k: maximum number of chunks to return.

    Returns:
        A formatted answer built directly from documentation chunks.
    """
    if allowed_sources is None:
        topic = detect_topic(query)
        sources = _TOPIC_SOURCES.get(topic, _DEFAULT_SOURCES)
    else:
        sources = allowed_sources

    chunks = search_knowledge(query, top_k=top_k, allowed_sources=sources)
    if not chunks:
        return (
            "No encontré información específica sobre eso en la documentación "
            "disponible. Prueba con otros términos o consulta la sección Docs."
        )

    lines = ["Aquí tienes información relacionada de la documentación:"]
    for chunk in chunks:
        title = chunk.title.lstrip("#").strip()
        lines.append(f"\n### {title}\n*{chunk.source}*\n{chunk.text}")
    return "\n".join(lines)
