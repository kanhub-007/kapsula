"""Read-model DTO for chunks consumed by search context expansion.

Carries only the attributes the application layer reads from a chunk.
Never an ORM instance — keeps the application layer decoupled from
SQLAlchemy (closes M5).
"""

from dataclasses import dataclass


@dataclass
class ChunkRead:
    """Read-model projection of a chunk for context expansion / citations."""

    id: int | None = None
    document_id: int | None = None
    sub_document_id: int | None = None
    chunk_index: int = 0
    content: str = ""
    token_count: int | None = None
    chunk_metadata: str | None = None
