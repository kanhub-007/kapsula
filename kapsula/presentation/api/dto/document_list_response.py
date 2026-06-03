from __future__ import annotations

from typing import List

from pydantic import BaseModel
from kapsula.presentation.api.dto.document_list_item import DocumentListItem


class DocumentListResponse(BaseModel):
    """Response model for document list."""

    documents: List[DocumentListItem]
    total: int
