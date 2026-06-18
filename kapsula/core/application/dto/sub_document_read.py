"""Read-model DTO for sub-documents consumed by search use cases.

Carries only the attributes ``MultiIndexSearcher`` and the metadata
builder read from a sub-document. Never an ORM instance — keeps the
application layer decoupled from SQLAlchemy.
"""

from dataclasses import dataclass


@dataclass
class SubDocumentRead:
    """Read-model projection of a sub-document for search routing."""

    id: int
    breadcrumb_key: str = ""
    page_count: int = 0
    faiss_index_path: str | None = None
    bm25_index_path: str | None = None
