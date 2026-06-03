"""Document domain entity — canonical model, never imports infrastructure."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Document:
    """A markdown document uploaded to the system."""

    id: int | None = None
    job_id: str = ""
    collection_id: int | None = None
    filename: str = ""
    size: int = 0
    created_at: datetime | None = None
    ip_address: str = ""
    duration: float | None = None
    content: str = ""
    status: str = "processing"
    doc_state: str = "active"
    faiss_index_path: str | None = None
    bm25_index_path: str | None = None

    # Navigation (populated by repository when loading)
    collection: Optional["Collection"] = None
    chunks: list["Chunk"] = field(default_factory=list)
    sub_documents: list["SubDocument"] = field(default_factory=list)
