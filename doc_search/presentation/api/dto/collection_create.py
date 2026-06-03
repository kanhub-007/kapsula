from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CollectionCreate(BaseModel):
    """Request model for creating a collection."""

    name: str
    account_id: Optional[str] = None  # Optional account ID to link collection to
