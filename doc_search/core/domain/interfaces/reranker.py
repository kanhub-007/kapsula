"""Reranker protocol."""

from typing import List, Dict, Any, Protocol


class Reranker(Protocol):
    """Interface for cross-encoder reranking backends."""

    async def rerank(
        self, query: str, candidates: List[Dict[str, Any]], top_k: int
    ) -> List[Dict[str, Any]]:
        """Rerank candidates and return the top *top_k*, each with a
        ``rerank_score`` key added."""
        ...
