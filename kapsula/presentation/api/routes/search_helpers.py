"""Search route helpers — citation extraction only.

Each route sub-module imports its own dependencies directly.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from kapsula.infrastructure.logging_config import get_logger

if TYPE_CHECKING:
    from kapsula.presentation.api.models import Citation

logger = get_logger(__name__)


def extract_citation_from_result(
    result: dict, db: Session, document_id: int = None
) -> Citation | None:
    """Extract citation information from a search result.

    Args:
        result: Search result dictionary containing chunk index.
        db: Database session.
        document_id: Document ID to filter chunks.

    Returns:
        Citation object or None if citation data not available.
    """
    from ..models import Citation

    try:
        chunk_index = result.get("index")
        if chunk_index is None:
            return None

        from kapsula.infrastructure.data import Chunk

        query = db.query(Chunk).filter(Chunk.chunk_index == chunk_index)

        if document_id is not None:
            query = query.filter(Chunk.document_id == document_id)

        sub_document_id = result.get("sub_document_id")
        if sub_document_id is not None:
            query = query.filter(Chunk.sub_document_id == sub_document_id)

        chunk = query.first()

        if not chunk or not chunk.chunk_metadata:
            return None

        metadata = json.loads(chunk.chunk_metadata)
        citation_data = metadata.get("citation")

        if not citation_data:
            return None

        return Citation(
            library_card_id=citation_data.get("library_card_id"),
            start_char=citation_data.get("start_char", 0),
            end_char=citation_data.get("end_char", 0),
            section_title=citation_data.get("section_title", ""),
            section_level=citation_data.get("section_level", ""),
        )
    except Exception as e:
        logger.warning("Failed to extract citation from result: %s", e)
        return None
