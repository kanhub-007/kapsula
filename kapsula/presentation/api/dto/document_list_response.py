from __future__ import annotations

from pydantic import BaseModel

from kapsula.presentation.api.dto.document_list_item import DocumentListItem


class DocumentListResponse(BaseModel):
    """Response model for document list."""

    documents: list[DocumentListItem]
    total: int
