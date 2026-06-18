from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class SearchRequest(BaseModel):
    """Request model for search."""

    query: str
    top_k: Optional[int] = 10
    dense_weight: Optional[float] = 0.5
    sparse_weight: Optional[float] = 0.5
