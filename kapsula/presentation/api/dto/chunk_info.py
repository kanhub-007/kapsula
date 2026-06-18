from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChunkInfo(BaseModel):
    """Chunk information."""

    id: int
    chunk_index: int
    content: str
    token_count: int | None
    metadata: dict[str, Any]
