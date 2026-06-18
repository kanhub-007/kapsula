from __future__ import annotations

from pydantic import BaseModel


class SearchRequest(BaseModel):
    """Request model for search."""

    query: str
    top_k: int | None = 10
    dense_weight: float | None = 0.5
    sparse_weight: float | None = 0.5
