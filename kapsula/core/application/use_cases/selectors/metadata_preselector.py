"""Cheap metadata pre-selection for routing candidates."""

from __future__ import annotations

from collections.abc import Iterable
from collections import Counter
from math import log

from kapsula.core.domain.text_processing import tokenize


class MetadataPreselector:
    """Rank routing candidates using cheap local metadata text.

    This intentionally stays simple and dependency-free. It approximates BM25
    enough to bound later LLM prompts while preserving recall with a minimum
    candidate count.
    """

    def __init__(self, max_candidates: int = 30, min_candidates: int = 5):
        self._max_candidates = max(1, max_candidates)
        self._min_candidates = max(1, min_candidates)

    def select(self, query: str, candidates: list[dict]) -> list[dict]:
        """Return candidates sorted by metadata relevance.

        Each returned candidate is copied and annotated with
        ``metadata_route_confidence`` and ``metadata_score``.
        """
        if not candidates:
            return []
        if len(candidates) <= self._min_candidates:
            return [self._annotate(candidate, 1.0, 1.0) for candidate in candidates]

        query_tokens = tokenize(query)
        if not query_tokens:
            return [
                self._annotate(candidate, 1.0, 1.0)
                for candidate in candidates[: self._max_candidates]
            ]

        docs = [tokenize(_candidate_text(candidate)) for candidate in candidates]
        doc_freq = Counter(token for doc in docs for token in set(doc))
        avg_len = sum(len(doc) for doc in docs) / max(1, len(docs))

        scored = []
        for candidate, doc_tokens in zip(candidates, docs):
            score = _bm25_like_score(
                query_tokens, doc_tokens, doc_freq, len(docs), avg_len
            )
            scored.append((score, candidate))

        scored.sort(key=lambda item: item[0], reverse=True)
        limit = min(len(scored), max(self._max_candidates, self._min_candidates))
        selected = scored[:limit]
        max_score = max((score for score, _ in selected), default=0.0)

        annotated = []
        for score, candidate in selected:
            confidence = _confidence(score, max_score)
            annotated.append(self._annotate(candidate, score, confidence))
        return annotated

    @staticmethod
    def _annotate(candidate: dict, score: float, confidence: float) -> dict:
        annotated = dict(candidate)
        annotated["metadata_score"] = score
        annotated["metadata_route_confidence"] = confidence
        return annotated


def _candidate_text(candidate: dict) -> str:
    parts: list[str] = []
    for key in (
        "name",
        "document_filename",
        "breadcrumb_key",
        "library_card_summary",
        "summary",
    ):
        value = candidate.get(key)
        if value:
            parts.append(str(value))
    for key in ("document_list", "page_titles"):
        value = candidate.get(key) or []
        if isinstance(value, Iterable) and not isinstance(value, str):
            parts.extend(str(item) for item in value)
    return "\n".join(parts)


def _bm25_like_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    doc_freq: Counter,
    total_docs: int,
    avg_len: float,
) -> float:
    if not doc_tokens:
        return 0.0
    counts = Counter(doc_tokens)
    k1 = 1.5
    b = 0.75
    doc_len = len(doc_tokens)
    score = 0.0
    for token in query_tokens:
        tf = counts[token]
        if tf == 0:
            continue
        idf = log(1 + (total_docs - doc_freq[token] + 0.5) / (doc_freq[token] + 0.5))
        denom = tf + k1 * (1 - b + b * doc_len / max(avg_len, 1))
        score += idf * (tf * (k1 + 1)) / denom
    return score


def _confidence(score: float, max_score: float) -> float:
    if max_score <= 0:
        return 0.6
    normalized = max(0.0, min(1.0, score / max_score))
    return 0.5 + 0.5 * normalized
