from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CollectionSearchRequest(BaseModel):
    """Request model for collection-level search."""

    query: str
    account_id: Optional[str] = None
    top_k: Optional[int] = 10
    rerank: Optional[bool] = False
    context_mode: Optional[str] = "none"
