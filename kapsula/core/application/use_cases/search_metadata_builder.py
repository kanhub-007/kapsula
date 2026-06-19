"""Builds collection and sub-document metadata for search routing."""

from __future__ import annotations

import json
import logging
from typing import Any

from kapsula.core.domain.interfaces.search_data_access import SearchDataAccess

logger = logging.getLogger(__name__)


class SearchMetadataBuilder:
    """Builds structured metadata lists from search data access for routing decisions."""

    def __init__(self, data: SearchDataAccess):
        self._data = data

    def build_subdoc_metadata(self, subdocs: list[Any]) -> list[dict]:
        """Build a list of metadata dicts for sub-document routing.

        Only includes sub-documents that have both FAISS and BM25 index paths.
        """
        metadata: list[dict] = []
        for sd in subdocs:
            if not sd.faiss_index_path or not sd.bm25_index_path:
                continue
            card = self._data.get_library_card_for_sub_doc(sd.id)
            page_titles = _parse_page_titles(card)
            metadata.append(
                {
                    "id": sd.id,
                    "breadcrumb_key": sd.breadcrumb_key,
                    "page_titles": page_titles,
                    "page_count": sd.page_count,
                    "faiss_path": sd.faiss_index_path,
                    "bm25_path": sd.bm25_index_path,
                }
            )
        return metadata

    def build_collection_metadata(self, collections: list[Any]) -> list[dict]:
        """Build a list of metadata dicts for collection routing.

        Each dict includes library card summary, document count, account
        GUID, and collection GUID. The summary is capped at 500 chars and
        falls back to a name-based label when no card exists, so LLM routing
        always has some context to chew on.
        """
        metadata: list[dict] = []
        for coll in collections:
            card = self._data.get_collection_library_card(coll.id)
            doc_count, doc_list, summary = _parse_collection_card(coll, card)
            metadata.append(
                {
                    "id": coll.id,
                    "name": coll.name,
                    "library_card_summary": summary,
                    "document_count": doc_count,
                    "document_list": doc_list,
                    "collection_route_confidence": 1.0,
                    "account_guid": _resolve_account_guid(coll),
                    "collection_guid": getattr(coll, "collection_id", None),
                }
            )
        return metadata

    def collect_collection_search_targets(
        self, collection: dict, docs: list[Any]
    ) -> tuple[list[dict], list[Any]]:
        """Split documents into sub-document candidates and single-index documents.

        Returns:
            Tuple of (subdoc_candidates, single_index_docs).
        """
        subdoc_candidates: list[dict] = []
        single_index_docs: list[Any] = []
        for doc in docs:
            subdocs = self._data.get_sub_documents(doc.id)
            if subdocs:
                for subdoc_meta in self.build_subdoc_metadata(subdocs):
                    subdoc_meta.update(
                        collection_id=collection["id"],
                        collection_name=collection["name"],
                        collection_route_confidence=collection.get(
                            "collection_route_confidence", 1.0
                        ),
                        document_id=doc.id,
                        document_filename=doc.filename,
                    )
                    subdoc_candidates.append(subdoc_meta)
            elif doc.faiss_index_path and doc.bm25_index_path:
                single_index_docs.append(doc)
        return subdoc_candidates, single_index_docs


# ── file-level parsing helpers ────────────────────────────


def _parse_page_titles(card: Any | None) -> list[str]:
    """Extract page titles from a library card's extra_metadata JSON."""
    if not (card and card.extra_metadata):
        return []
    try:
        return json.loads(card.extra_metadata).get("page_titles", [])
    except json.JSONDecodeError:
        return []


def _parse_collection_card(coll: Any, card: Any | None) -> tuple[int, list[str], str]:
    """Extract document_count, document_list, and summary from a collection library card.

    Summary is capped at 500 chars and falls back to a name-based label when
    no card exists (closes M5: the duplicate builder in
    PrepareIntelligentSearchUseCase did this; the single source of truth now
    does too).
    """
    fallback = f"Collection: {getattr(coll, 'name', '?')}"
    if not (card and card.extra_metadata):
        return 0, [], (card.content[:500] if card else fallback)
    try:
        meta = json.loads(card.extra_metadata)
        return (
            meta.get("total_documents", 0),
            [d["filename"] for d in meta.get("document_summaries", [])],
            (card.content or fallback)[:500],
        )
    except json.JSONDecodeError:
        return 0, [], (card.content or fallback)[:500]


def _resolve_account_guid(coll: Any) -> str | None:
    """Return the account GUID from a collection read-model or ORM object.

    Prefers the flat ``account_guid`` field carried by ``CollectionRead``
    DTOs; falls back to the legacy ``coll.account.account_id`` ORM path
    for any caller still passing ORM instances.
    """
    flat = getattr(coll, "account_guid", None)
    if flat is not None:
        return flat
    account = getattr(coll, "account", None)
    return getattr(account, "account_id", None) if account else None
