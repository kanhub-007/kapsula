from __future__ import annotations

from pydantic import BaseModel

from kapsula.presentation.api.dto.document_export_info import DocumentExportInfo
from kapsula.presentation.api.dto.library_card_info import LibraryCardInfo


class CollectionExportInfo(BaseModel):
    """Complete collection information for export."""

    collection_id: str
    name: str
    logo_url: str | None = None
    created_at: str
    document_count: int
    documents: list[DocumentExportInfo]
    library_cards: list[LibraryCardInfo]  # Collection-level library cards
