"""Search route helpers — shared imports and citation extraction."""

import json
import os
from typing import Optional

from fastapi import HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from kapsula.core.application.dto.collection_search import CollectionSearch
from kapsula.core.application.dto.single_index_search import SingleIndexSearch
from kapsula.core.application.dto.sub_document_search import SubDocumentSearch
from kapsula.core.domain.text_processing import parse_node_type_filter
from kapsula.infrastructure.data.connection import get_db
from kapsula.infrastructure.data.tables.collection import Collection
from kapsula.infrastructure.data.tables.document import Document
from kapsula.infrastructure.data.tables.library_card import LibraryCard
from kapsula.infrastructure.data.tables.sub_document import SubDocument
from kapsula.infrastructure.logging_config import get_logger
from kapsula.presentation.api.search_presenter import (
    build_collection_search_response,
    collect_unique_citations,
)
from kapsula.startup import (
    create_multi_index_searcher,
    create_query_planner,
    create_intelligent_searcher,
    create_chat_client,
)

logger = get_logger(__name__)


def extract_citation_from_result(
    result: dict, db: Session, document_id: int = None
) -> Optional["Citation"]:
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
