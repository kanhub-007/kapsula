"""Read-model DTO for library cards consumed by search use cases.

Carries only the attributes the application layer reads from a library
card. Never an ORM instance — keeps the application layer decoupled from
SQLAlchemy (closes M5).
"""

from dataclasses import dataclass


@dataclass
class LibraryCardRead:
    """Read-model projection of a library card for search metadata."""

    id: int | None = None
    doc_id: str | None = None
    level: str = ""
    title: str = ""
    content: str = ""
    extra_metadata: str | None = None
    collection_id: int | None = None
    document_id: int | None = None
    sub_document_id: int | None = None
    description: str | None = None
    card_type: str | None = None
    importance: float | None = None
