"""Keyword + BM25 RAG over markdown knowledge files.

Files live in `backend/ai/knowledge/`. The service loads them at startup and
exposes a reload endpoint so new/updated documents can be picked up without
restarting the backend.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from loguru import logger


KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "ai" / "knowledge"

# BM25 parameters
_K1 = 1.5
_B = 0.75


@dataclass
class Chunk:
    source: str
    title: str
    text: str
    is_header: bool = False


class KnowledgeBase:
    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory) if directory else KNOWLEDGE_DIR
        self.chunks: list[Chunk] = []
        self._tokenized: list[list[str]] = []
        self._avgdl: float = 0.0
        self._idf: dict[str, float] = {}
        self.load()

    def load(self) -> None:
        self.chunks = []
        self._tokenized = []
        self._avgdl = 0.0
        self._idf = {}

        if not self.directory.exists():
            logger.warning(f"[knowledge] Directory does not exist: {self.directory}")
            return

        for path in sorted(self.directory.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
                for chunk in _split_into_chunks(path.name, text):
                    self.chunks.append(chunk)
                    source_tag = chunk.source.replace(".md", "").replace("_", " ")
                    self._tokenized.append(
                        _tokenize(chunk.title + " " + chunk.text + " " + source_tag)
                    )
            except Exception as exc:
                logger.warning(f"[knowledge] Failed to load {path}: {exc}")

        if self.chunks:
            total_len = sum(len(t) for t in self._tokenized)
            self._avgdl = total_len / len(self._tokenized)
            self._compute_idf()

        logger.info(
            f"[knowledge] Loaded {len(self.chunks)} chunks from {self.directory}"
        )

    def reload(self) -> dict:
        before = len(self.chunks)
        self.load()
        return {"status": "reloaded", "chunks_before": before, "chunks_after": len(self.chunks)}

    def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        """BM25 keyword-based retrieval with small title/source boosts."""
        query_terms = _extract_query_terms(query)
        if not query_terms:
            return []

        scored: list[tuple[float, Chunk]] = []
        n = len(self.chunks)
        if n == 0:
            return []

        for idx, chunk in enumerate(self.chunks):
            tokens = self._tokenized[idx]
            if chunk.is_header or not chunk.text.strip():
                continue

            score = 0.0
            for term in query_terms:
                idf = self._idf.get(term, 0.0)
                if idf == 0.0:
                    continue
                tf = tokens.count(term)
                if tf:
                    dl = len(tokens)
                    denom = tf + _K1 * (1 - _B + _B * (dl / self._avgdl))
                    score += idf * (tf * (_K1 + 1)) / denom

            if score <= 0:
                continue

            # Title boost: exact term matches in the chunk title are strong signals.
            title_tokens = _tokenize(chunk.title)
            title_hits = sum(1 for term in query_terms if term in title_tokens)
            score += title_hits * 4.0

            # Source/intent boost: platform questions should prefer platform docs.
            score += _intent_source_boost(query_terms, chunk)

            # Definition boost: when the user asks "what is X", strongly prefer
            # chunks whose title contains the technical term being asked about.
            score += _definition_boost(query_terms, chunk)
            # Focused definition titles (e.g. "## Order Block (OB)") beat
            # sub-variant titles (e.g. "Inverted Fair Value Gap").
            score += _focused_definition_boost(query_terms, chunk)
            # Direct definition sentences ("Un FVG es...") beat sub-topic descriptions.
            score += _direct_definition_boost(query_terms, chunk)

            # Deprioritize generic file headers.
            if chunk.is_header:
                score -= 6.0

            # Slight length normalization so giant generic sections do not dominate.
            normalized = score / (max(len(chunk.text), 1) ** 0.2)
            scored.append((normalized, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def _compute_idf(self) -> None:
        df: dict[str, int] = {}
        for tokens in self._tokenized:
            seen = set(tokens)
            for term in seen:
                df[term] = df.get(term, 0) + 1

        n = len(self._tokenized)
        self._idf = {}
        for term, freq in df.items():
            # idf smoothing
            idf = math.log((n - freq + 0.5) / (freq + 0.5) + 1.0)
            self._idf[term] = idf


# ─── helpers ─────────────────────────────────────────────────────────

_CANONICAL = {
    "trading view": "tradingview",
    "tradingview": "tradingview",
    "order block": "orderblock",
    "orderblock": "orderblock",
    "fair value gap": "fvg",
    "fvg": "fvg",
    "change of character": "choch",
    "choch": "choch",
    "breaker block": "breakerblock",
    "breakerblock": "breakerblock",
    "mitigation block": "mitigationblock",
    "mitigationblock": "mitigationblock",
    "imbalance": "imbalance",
    "liquidity void": "liquidityvoid",
    "liquidityvoid": "liquidityvoid",
    "smart money concepts": "smc",
    "smc": "smc",
    "inner circle trader": "ict",
    "ict": "ict",
    "paper trading": "papertrading",
    "papertrading": "papertrading",
}

_STOP_WORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "pero",
    "de", "del", "al", "a", "ante", "bajo", "con", "contra", "desde", "en",
    "entre", "hacia", "hasta", "para", "por", "según", "sin", "sobre", "tras",
    "que", "como", "cuando", "donde", "quien", "cuyo", "cuya", "cuyos", "cuyas",
    "lo", "le", "les", "me", "te", "se", "nos", "os", "mi", "tu", "su", "sus",
    "mío", "mía", "tuyo", "tuya", "suyo", "suya", "nuestro", "vuestra",
    "qué", "que", "cuál", "cuáles", "cuando", "cuándo", "donde", "dónde", "porqué", "porque",
    "es", "son", "está", "están", "fue", "fueron", "ser", "estar", "haber",
    "tengo", "tiene", "tenemos", "tienen", "hay", "este", "esta", "estos", "estas",
    "ese", "esa", "esos", "esas", "aquel", "aquella", "aquellos", "aquellas",
    "explicas", "explicar", "dime", "cuéntame", "cuentame", "digas", "decir",
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for",
    "with", "from", "by", "about", "as", "into", "through", "during", "before",
    "after", "above", "below", "between", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "must", "can", "this", "that", "these", "those", "i", "you",
    "he", "she", "it", "we", "they", "him", "her", "us", "them",
}


_SOURCE_INTENTS = {
    "platform_guide.md": {
        "bot", "bots", "plataforma", "plataform", "tradingview", "tradingview",
        "webhook", "webhooks", "conectar", "conexión", "conexion", "configurar",
        "configuración", "configuracion", "crear", "nuevo", "dashboard",
        "componentes", "paper", "papertrading", "shadow", "anti-fake", "antifake",
    },
    "ict_smc_definitions.md": {
        "orderblock", "order block", "fvg", "fair value gap", "choch",
        "change of character", "liquidity", "imbalance", "breaker", "mitigation",
        "smc", "ict", "conceptos", "definición", "definicion",
    },
    "internal_indicators.md": {
        "indicador", "indicadores", "scanner", "señal", "señales", "signal",
        "score", "tier", "probabilidad", "live", "modelo", "modelos",
    },
    "market_notes.md": {
        "mercado", "bitcoin", "btc", "ethereum", "eth", "nota", "notas",
        "macro", "evento", "eventos", "calendario",
    },
    "tradingview_integration.md": {
        "tradingview", "trading", "view", "webhook", "webhooks", "conectar",
        "conexion", "conexión", "alerta", "alertas", "pine", "json", "endpoint",
        "bot_id", "secret",
    },
    "QUANTUM_BASE_CONOCIMIENTO_SMC_ICT.md": {
        "smc", "ict", "orderblock", "fvg", "choch", "liquidity", "mitigation",
        "breaker", "imbalance", "kill zone", "killzone", "org", "session",
        "sesión", "sesion", "premium", "discount", "fair value gap",
        "change of character", "psicología", "psicologia", "trading en la zona",
        "mark douglas",
    },
}


def _tokenize(text: str) -> list[str]:
    """Lowercase, canonicalize compound terms, remove punctuation and stop words."""
    lowered = text.lower()
    # Map common multi-word phrases to canonical single tokens so titles like
    # "Order Block" are indexed as "orderblock" and match "order block" queries.
    for phrase, canonical in sorted(_CANONICAL.items(), key=lambda x: -len(x[0])):
        lowered = re.sub(rf"\b{re.escape(phrase)}\b", canonical, lowered)

    lowered = re.sub(r"[^\w\s]", " ", lowered)
    return [
        w.strip()
        for w in lowered.split()
        if w.strip() and w.strip() not in _STOP_WORDS and len(w.strip()) > 1
    ]


def _extract_query_terms(query: str) -> list[str]:
    """Normalize query and map common synonyms to canonical forms."""
    lowered = query.lower()
    # Replace multi-word canonical terms first so they are treated as single tokens.
    for phrase, canonical in sorted(_CANONICAL.items(), key=lambda x: -len(x[0])):
        lowered = re.sub(rf"\b{re.escape(phrase)}\b", canonical, lowered)

    tokens = _tokenize(lowered)
    # Expand acronyms only: add canonical form if an acronym is present.
    expanded: set[str] = set(tokens)
    for token in tokens:
        if token in _CANONICAL and token != _CANONICAL[token]:
            expanded.add(_CANONICAL[token])
    return list(expanded)


def _definition_boost(query_terms: list[str], chunk: Chunk) -> float:
    """Boost chunks whose title directly names a specific technical term in the query.

    Broad domain terms such as ICT or SMC are excluded because they appear in many
    titles and would otherwise drown out the concrete concept being asked about.
    Generic file headers and section headers that list several variants
    (e.g. "FVG / BISI / SIBI") are skipped.
    """
    if chunk.is_header or "/" in chunk.title:
        return 0.0
    boost = 0.0
    title_tokens = set(_tokenize(chunk.title))
    definable_terms = set(_CANONICAL.values()) - {"ict", "smc"}
    for term in query_terms:
        if term not in definable_terms:
            continue
        if term in title_tokens:
            boost += 12.0
    return boost


def _focused_definition_boost(query_terms: list[str], chunk: Chunk) -> float:
    if chunk.is_header or "/" in chunk.title:
        return 0.0
    title_tokens = _tokenize(chunk.title)
    if len(title_tokens) > 3:
        return 0.0
    definable_terms = set(_CANONICAL.values()) - {"ict", "smc"}
    title_set = set(title_tokens)
    if any(term in title_set for term in query_terms if term in definable_terms):
        return 6.0
    return 0.0


def _direct_definition_boost(query_terms: list[str], chunk: Chunk) -> float:
    """Boost chunks that start with a plain definition sentence for the term."""
    text_start = chunk.text[:120].lower()
    definable_terms = set(_CANONICAL.values()) - {"ict", "smc"}
    for term in query_terms:
        if term not in definable_terms:
            continue
        if re.search(rf"\b{re.escape(term)}\s+es\b", text_start):
            return 4.0
    return 0.0


def _intent_source_boost(query_terms: list[str], chunk: Chunk) -> float:
    """Boost chunks whose source matches the intent of the query."""
    boost = 0.0
    query_set = set(query_terms)
    for source, intent_terms in _SOURCE_INTENTS.items():
        if source.lower() not in chunk.source.lower():
            continue
        overlap = query_set & intent_terms
        if overlap:
            # Specific integration docs get the highest boost; platform guide is next.
            if source == "tradingview_integration.md":
                multiplier = 3.0
                # Integration guides should dominate over generic platform docs.
                boost += 5.0
            elif source == "platform_guide.md":
                multiplier = 2.0
            else:
                multiplier = 1.5
            boost += len(overlap) * multiplier
    return boost


def _split_into_chunks(filename: str, text: str) -> Iterable[Chunk]:
    """Split markdown into chunks by ## / ### / #### headers.

    The first chunk (content before the first header) is marked as a file header;
    it is usually too generic to be useful as a primary result.
    """
    lines = text.splitlines()
    current_title = filename.replace(".md", "").replace("_", " ").title()
    current_lines: list[str] = []
    first_chunk = True

    for line in lines:
        if line.startswith(("## ", "### ", "#### ")):
            if current_lines:
                yield Chunk(
                    source=filename,
                    title=current_title,
                    text="\n".join(current_lines).strip(),
                    is_header=first_chunk,
                )
                first_chunk = False
            current_title = re.sub(r"^#{2,4}\\s+", "", line).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        yield Chunk(
            source=filename,
            title=current_title,
            text="\n".join(current_lines).strip(),
            is_header=first_chunk,
        )


# Global singleton knowledge base
_knowledge_base: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = KnowledgeBase()
    return _knowledge_base


def reload_knowledge() -> dict:
    return get_knowledge_base().reload()


def search_knowledge(query: str, top_k: int = 5) -> list[Chunk]:
    return get_knowledge_base().search(query, top_k)
