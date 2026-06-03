"""Chunker protocol."""

from typing import List, Dict, Any, Protocol


class Chunker(Protocol):
    """Interface for document chunking backends."""

    def chunk(self, content: str) -> List[Dict[str, Any]]:
        """Split *content* into token-bounded chunks with metadata."""
        ...
