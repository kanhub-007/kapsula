"""Reranker protocol."""

from typing import Any, Protocol


class Reranker(Protocol):
    """Interface for cross-encoder reranking backends."""

    async def rerank(
        self, query: str, candidates: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        """Rerank candidates and return the top *top_k*, each with a
        ``rerank_score`` key added."""
        ...
