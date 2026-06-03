"""Retriever protocol."""

from typing import List, Dict, Any, Protocol


class Retriever(Protocol):
    """Interface for document retrieval backends."""

    async def retrieve(self, query: str, k: int) -> List[Dict[str, Any]]:
        """Return top-k results for *query*."""
        ...
