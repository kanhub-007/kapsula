"""Chunk domain entity."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Chunk:
    id: int | None = None
    document_id: int | None = None
    sub_document_id: int | None = None
    content: str = ""
    chunk_index: int = 0
    token_count: int | None = None
    chunk_metadata: str | None = None
    created_at: datetime | None = None
