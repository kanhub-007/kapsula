"""Searcher protocol — the contract for a single-index hybrid searcher.

Closes M4: :class:`MultiIndexSearcher` previously took a
``Callable[[str, str], Any]`` factory and then ``await``-ed the result with an
implicit ``.search(...)`` contract that was invisible to type-checkers. This
Protocol makes the contract explicit.
"""

from __future__ import annotations

from typing import Protocol


class Searcher(Protocol):
    """Searches one FAISS+BM25 index pair for a query."""

    async def search(
        self,
        query: str,
        top_k: int = 10,
        retrieval_k: int = 50,
        rerank: bool = False,
        node_type_filter: list[str] | None = None,
        sub_document_id: int | None = None,
    ) -> list[dict]:
        """Return ranked result dicts for *query* against this index."""
        ...
