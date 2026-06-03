from __future__ import annotations

from typing import List

from pydantic import BaseModel
from doc_search.presentation.api.dto.chunk_info import ChunkInfo
from doc_search.presentation.api.dto.document_info import DocumentInfo


class ChunksDownloadResponse(BaseModel):
    """Response model for downloading chunks as JSON."""

    document: DocumentInfo
    chunks: List[ChunkInfo]
    total_chunks: int
