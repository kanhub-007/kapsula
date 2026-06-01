"""Document domain entity."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Document:
    id: int | None = None
    job_id: str = ""
    collection_id: int | None = None
    filename: str = ""
    size: int = 0
    created_at: datetime | None = None
    duration: float | None = None
    content: str = ""
    status: str = "processing"
    faiss_index_path: str | None = None
    bm25_index_path: str | None = None
