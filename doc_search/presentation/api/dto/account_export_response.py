from __future__ import annotations

from typing import List

from pydantic import BaseModel
from doc_search.presentation.api.dto.collection_export_info import CollectionExportInfo


class AccountExportResponse(BaseModel):
    """Complete account export with all data."""

    account_id: str
    name: str
    created_at: str
    collection_count: int
    total_documents: int
    total_library_cards: int
    collections: List[CollectionExportInfo]
