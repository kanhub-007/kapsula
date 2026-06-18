"""Chunker protocol."""

from typing import Any, Protocol


class Chunker(Protocol):
    """Interface for document chunking backends."""

    def chunk(self, content: str) -> list[dict[str, Any]]:
        """Split *content* into token-bounded chunks with metadata."""
        ...
