"""Reranker protocol."""

from typing import Any, Protocol

# Default cross-encoder score below which a candidate is considered off-topic.
# Shared by both reranker implementations so they stay behaviourally
# consistent (closes M11). Overridable per instance.
DEFAULT_RERANK_THRESHOLD = 0.2


class Reranker(Protocol):
    """Interface for cross-encoder reranking backends.

    Contract: implementations add a ``rerank_score`` key to each candidate
    dict. They MAY mutate the input candidate dicts in place; callers that
    need the original order/scores should pass a copy.
    """

    async def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        """Rerank candidates and return the top *top_k*, each with a
        ``rerank_score`` key added."""
        ...
