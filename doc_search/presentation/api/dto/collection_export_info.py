from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel
from doc_search.presentation.api.dto.document_export_info import DocumentExportInfo
from doc_search.presentation.api.dto.library_card_info import LibraryCardInfo


class CollectionExportInfo(BaseModel):
    """Complete collection information for export."""

    collection_id: str
    name: str
    logo_url: Optional[str] = None
    created_at: str
    document_count: int
    documents: List[DocumentExportInfo]
    library_cards: List[LibraryCardInfo]  # Collection-level library cards
