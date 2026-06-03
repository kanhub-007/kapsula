from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel
from doc_search.presentation.api.dto.library_card_info import LibraryCardInfo


class DocumentExportInfo(BaseModel):
    """Complete document information for export."""

    id: int
    job_id: str
    filename: str
    size: int
    status: str
    created_at: str
    duration: Optional[float]
    chunk_count: int
    library_cards: List[LibraryCardInfo]
