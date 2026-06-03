from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel


class ChunkInfo(BaseModel):
    """Chunk information."""

    id: int
    chunk_index: int
    content: str
    token_count: Optional[int]
    metadata: Dict[str, Any]
