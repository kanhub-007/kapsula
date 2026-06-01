"""DocumentStructure domain entity."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class DocumentStructure:
    id: int | None = None
    document_id: int | None = None
    skeleton_structure: str = ""
    created_at: datetime | None = None
