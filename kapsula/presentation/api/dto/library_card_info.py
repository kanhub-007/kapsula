from __future__ import annotations

from pydantic import BaseModel


class LibraryCardInfo(BaseModel):
    """Library card information."""

    id: int
    level: str
    title: str
    content: str
    created_at: str
