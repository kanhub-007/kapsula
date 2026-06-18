"""Builds document-structure metadata from ORM for intelligent search planning.

Used by both API routes and MCP tools to avoid duplication when preparing
document/section hierarchies for LLM query planning.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from kapsula.infrastructure.data.tables.library_card import (
    LibraryCard as OrmLibraryCard,
)
from kapsula.infrastructure.data.tables.sub_document import (
    SubDocument as OrmSubDocument,
)


def build_document_structure_from_subdocs(
    subdocs: list[OrmSubDocument],
    db: Session,
) -> list[dict]:
    """Build a hierarchical structure list from sub-documents for query planning.

    Each entry is ``{"subdocument_name": str, "sections": [{"level": str, "title": str}]}``.
    """
    result: list[dict] = []
    for subdoc in subdocs:
        cards = _fetch_hierarchy_cards(db, sub_document_id=subdoc.id)
        if cards:
            result.append(
                {
                    "subdocument_name": subdoc.breadcrumb_key,
                    "sections": _cards_to_sections(cards),
                }
            )
    return result


def build_document_structure_from_document(
    document_id: int,
    fallback_name: str,
    db: Session,
    limit: int = 20,
) -> list[dict]:
    """Build a hierarchical structure list from a single-index document.

    For documents without sub-documents, uses document-level library cards.
    """
    cards = _fetch_hierarchy_cards(db, document_id=document_id, limit=limit)
    if cards:
        return [
            {
                "subdocument_name": fallback_name,
                "sections": _cards_to_sections(cards),
            }
        ]
    return []


# ── internal helpers ────────────────────────────────────


def _fetch_hierarchy_cards(
    db: Session,
    *,
    sub_document_id: int | None = None,
    document_id: int | None = None,
    limit: int = 20,
) -> list:
    """Fetch level_1/level_2/level_3 library cards for a sub-document or document."""
    query = db.query(OrmLibraryCard).filter(
        OrmLibraryCard.level.in_(["level_1", "level_2", "level_3"])
    )
    if sub_document_id is not None:
        query = query.filter(OrmLibraryCard.sub_document_id == sub_document_id)
    elif document_id is not None:
        query = query.filter(
            OrmLibraryCard.document_id == document_id,
            OrmLibraryCard.sub_document_id.is_(None),
        )
    else:
        return []
    return query.order_by(OrmLibraryCard.level.desc()).limit(limit).all()


def _cards_to_sections(cards: list) -> list[dict]:
    """Convert library card list to sections list."""
    return [{"level": c.level, "title": c.title} for c in cards]
