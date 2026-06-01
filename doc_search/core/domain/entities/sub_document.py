"""SubDocument domain entity."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SubDocument:
    id: int | None = None
    document_id: int | None = None
    breadcrumb_key: str = ""
    breadcrumb_level: int = 0
    faiss_index_path: str | None = None
    bm25_index_path: str | None = None
    page_count: int = 0
    created_at: datetime | None = None
