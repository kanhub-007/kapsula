"""Retriever protocol."""

from typing import Any, Protocol


class Retriever(Protocol):
    """Interface for document retrieval backends."""

    async def retrieve(self, query: str, k: int) -> list[dict[str, Any]]:
        """Return top-k results for *query*."""
        ...
