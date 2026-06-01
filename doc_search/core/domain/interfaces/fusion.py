"""Fusion method protocol for combining dense and sparse results."""

from typing import List, Dict, Any, Protocol


class Fusion(Protocol):
    """Interface for fusing dense and sparse retrieval results."""

    def fuse(
        self, dense: List[Dict[str, Any]], sparse: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Combine results and return scored, sorted list."""
        ...
