from __future__ import annotations

from pydantic import BaseModel

from kapsula.presentation.api.dto.library_card_info import LibraryCardInfo


class DocumentExportInfo(BaseModel):
    """Complete document information for export."""

    id: int
    job_id: str
    filename: str
    size: int
    status: str
    created_at: str
    duration: float | None
    chunk_count: int
    library_cards: list[LibraryCardInfo]
