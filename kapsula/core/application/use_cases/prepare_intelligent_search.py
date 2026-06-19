"""Prepare an intelligent collection search — shared by API and MCP.

Closes A6/D5/O1: previously the API route (``_intelligent_search_prepare``)
and the MCP tool (``_search_helpers._db_work``) duplicated the same
5-step flow (query collections -> build metadata -> route -> build document
structure -> plan). This single use case is the one place that flow lives.
"""

import logging
from collections.abc import Callable

from kapsula.core.application.dto.search_preparation import SearchPreparation
from kapsula.core.application.use_cases.search_metadata_builder import (
    SearchMetadataBuilder,
)
from kapsula.core.domain.interfaces.chat_client import ChatClient
from kapsula.core.domain.interfaces.search_data_access import SearchDataAccess

logger = logging.getLogger(__name__)

#: Callable that returns the hierarchical document structure for a collection.
StructureBuilder = Callable[[int], list[dict]]


class PrepareIntelligentSearchUseCase:
    """Route to a collection, build document structure, and create a query plan."""

    def __init__(
        self,
        data: SearchDataAccess,
        chat_client: ChatClient,
        query_planner,
        collection_selector,
        structure_builder: StructureBuilder,
    ):
        self._data = data
        self._chat_client = chat_client
        self._query_planner = query_planner
        self._collection_selector = collection_selector
        self._structure_builder = structure_builder
        self._metadata = SearchMetadataBuilder(data)

    def prepare(
        self,
        query: str,
        account_id: str | None,
        enable_planning: bool,
    ) -> SearchPreparation:
        """Return a :class:`SearchPreparation` for the given query.

        Raises ``ValueError`` when no collections are available for the scope.
        """
        collections = self._load_collections(account_id)
        if not collections:
            logger.warning("No collections found for account_id=%s", account_id)
            raise ValueError("No collections available")

        metadata = self._build_collection_metadata(collections)
        routed_collection = self._route(query, collections, metadata)
        document_structure = self._build_document_structure(routed_collection)

        plan = None
        if enable_planning and document_structure:
            logger.info(
                "Creating query plan using %s sections from routed collection",
                len(document_structure),
            )
            plan = self._query_planner.plan_document_search(
                query, document_library_card=None, document_structure=document_structure
            )
            logger.info(
                "Query plan: %s - %s",
                plan["strategy"],
                plan.get("reasoning", ""),
            )

        return SearchPreparation(
            plan=plan,
            collections=collections,
            routed_collection=routed_collection,
            document_structure=document_structure,
        )

    # ── steps ────────────────────────────────────────────────

    def _load_collections(self, account_id: str | None):
        if account_id:
            return self._data.get_collections_by_account(account_id)
        return self._data.get_all_collections()

    def _build_collection_metadata(self, collections) -> list[dict]:
        # Delegate to the single shared builder (closes M5 — this was a
        # near-duplicate of SearchMetadataBuilder.build_collection_metadata).
        return self._metadata.build_collection_metadata(collections)

    def _route(self, query, collections, metadata: list[dict]):
        routed_ids = self._collection_selector.select(query, metadata)
        routed_id = routed_ids[0] if routed_ids else collections[0].id
        logger.info("Routed to collection ID: %s", routed_id)
        return next((c for c in collections if c.id == routed_id), collections[0])

    def _build_document_structure(self, routed_collection) -> list[dict]:
        if routed_collection is None:
            return []
        return self._structure_builder(routed_collection.id)
