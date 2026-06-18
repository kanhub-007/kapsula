"""Shared intelligent search preparation logic."""

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from kapsula.infrastructure.data.tables.collection import Collection as OrmCollection
from kapsula.infrastructure.data.tables.document import Document as OrmDocument
from kapsula.infrastructure.data.tables.library_card import (
    LibraryCard as OrmLibraryCard,
)
from kapsula.infrastructure.data.tables.sub_document import (
    SubDocument as OrmSubDocument,
)
from kapsula.startup import create_chat_client, create_query_planner

logger = logging.getLogger(__name__)


async def _prepare_intelligent_search(
    query: str,
    account_id: str | None,
    enable_planning: bool,
    db: Session,
):
    """Route to collection, build document structure, create query plan.

    Returns (search_plan, collections, routed_collection) tuple or raises HTTPException.
    """
    from kapsula.core.application.use_cases.selectors.collection_selector import (
        CollectionSelector,
    )

    collections_query = db.query(OrmCollection)
    if account_id:
        collections_query = collections_query.join(OrmCollection.account).filter(
            OrmCollection.account.has(account_id=account_id)
        )
    collections = collections_query.all()

    if not collections:
        logger.warning("No collections found")
        raise HTTPException(status_code=404, detail="No collections available")

    router = CollectionSelector(create_chat_client())
    collection_metadata = []
    for coll in collections:
        card = (
            db.query(OrmLibraryCard)
            .filter(
                OrmLibraryCard.collection_id == coll.id,
                OrmLibraryCard.level == "collection",
            )
            .first()
        )
        collection_metadata.append(
            {
                "id": coll.id,
                "name": coll.name,
                "library_card_summary": (
                    card.content[:500] if card else f"Collection: {coll.name}"
                ),
                "document_count": len(coll.documents),
            }
        )

    routed_collection_ids = router.select(query, collection_metadata)
    routed_collection_id = (
        routed_collection_ids[0] if routed_collection_ids else collections[0].id
    )
    logger.info("Routed to collection ID: %s", routed_collection_id)

    routed_collection = (
        db.query(OrmCollection).filter(OrmCollection.id == routed_collection_id).first()
    )

    from kapsula.presentation.shared.document_structure_builder import (
        build_document_structure_from_subdocs,
    )

    document_structure = []
    if routed_collection:
        documents = (
            db.query(OrmDocument)
            .filter(OrmDocument.collection_id == routed_collection_id)
            .all()
        )
        for doc in documents:
            subdocs = (
                db.query(OrmSubDocument)
                .filter(OrmSubDocument.document_id == doc.id)
                .all()
            )
            document_structure.extend(
                build_document_structure_from_subdocs(subdocs, db)
            )

    search_plan = None
    if enable_planning and document_structure:
        logger.info(
            "Creating query plan using %s sections from routed collection",
            len(document_structure),
        )
        planner = create_query_planner()
        search_plan = planner.plan_document_search(
            query, document_library_card=None, document_structure=document_structure
        )
        logger.info(
            "Query plan: %s - %s",
            search_plan["strategy"],
            search_plan.get("reasoning", ""),
        )

    return search_plan, collections, routed_collection
