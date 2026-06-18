from __future__ import annotations

from pydantic import BaseModel


class CollectionSearchRequest(BaseModel):
    """Request model for collection-level search."""

    query: str
    account_id: str | None = None
    top_k: int | None = 10
    context_mode: str | None = "none"
