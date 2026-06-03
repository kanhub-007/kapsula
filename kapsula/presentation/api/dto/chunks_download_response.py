from __future__ import annotations

from typing import List

from pydantic import BaseModel
from kapsula.presentation.api.dto.chunk_info import ChunkInfo
from kapsula.presentation.api.dto.document_info import DocumentInfo


class ChunksDownloadResponse(BaseModel):
    """Response model for downloading chunks as JSON."""

    document: DocumentInfo
    chunks: List[ChunkInfo]
    total_chunks: int
