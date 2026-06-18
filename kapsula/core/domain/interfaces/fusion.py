"""Fusion method protocol for combining dense and sparse results."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Fusion(Protocol):
    """Interface for fusing dense and sparse retrieval results."""

    def fuse(
        self, dense: list[dict[str, Any]], sparse: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Combine results and return scored, sorted list."""
        ...
