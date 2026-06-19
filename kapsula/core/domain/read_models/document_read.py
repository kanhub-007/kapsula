"""Read-model DTO for documents consumed by search use cases."""

from dataclasses import dataclass


@dataclass
class DocumentRead:
    """Read-model projection of a completed document for search routing."""

    id: int
    filename: str = ""
    collection_id: int | None = None
    faiss_index_path: str | None = None
    bm25_index_path: str | None = None
