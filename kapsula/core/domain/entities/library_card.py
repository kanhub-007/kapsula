"""LibraryCard domain entity."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class LibraryCard:
    id: int | None = None
    collection_id: int | None = None
    document_id: int | None = None
    sub_document_id: int | None = None
    doc_id: str = ""
    level: str = ""
    title: str = ""
    content: str = ""
    extra_metadata: str | None = None
    created_at: datetime | None = None
