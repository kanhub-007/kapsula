"""Shared intelligent search preparation logic."""

async def _prepare_intelligent_search(query, account_id, enable_planning, db):
    """Route to collection, build document structure, create query plan.
    
    Returns (search_plan, collections, routed_collection) tuple or raises HTTPException.
    """
    from kapsula.core.application.use_cases.selectors.collection_selector import CollectionSelector

    collections_query = db.query(Collection)
    if account_id:
        collections_query = collections_query.join(Collection.account).filter(
            Collection.account.has(account_id=account_id)
        )
    collections = collections_query.all()

    if not collections:
        logger.warning("No collections found")
        raise HTTPException(status_code=404, detail="No collections available")

    router = CollectionSelector(create_chat_client())
    collection_metadata = []
    for coll in collections:
        card = (
            db.query(LibraryCard)
            .filter(
                LibraryCard.collection_id == coll.id,
                LibraryCard.level == "collection",
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
    logger.info(f"Routed to collection ID: {routed_collection_id}")

    routed_collection = (
        db.query(Collection).filter(Collection.id == routed_collection_id).first()
    )

    from kapsula.presentation.shared.document_structure_builder import (
        build_document_structure_from_subdocs,
    )
    document_structure = []
    if routed_collection:
        documents = (
            db.query(Document)
            .filter(Document.collection_id == routed_collection_id)
            .all()
        )
        for doc in documents:
            subdocs = (
                db.query(SubDocument)
                .filter(SubDocument.document_id == doc.id)
                .all()
            )
            document_structure.extend(
                build_document_structure_from_subdocs(subdocs, db)
            )

    search_plan = None
    if enable_planning and document_structure:
        logger.info(
            f"Creating query plan using {len(document_structure)} sections from routed collection"
        )
        planner = create_query_planner()
        search_plan = planner.plan_document_search(
            query, document_library_card=None, document_structure=document_structure
        )
        logger.info(
            f"Query plan: {search_plan['strategy']} - {search_plan.get('reasoning', '')}"
        )

    return search_plan, collections, routed_collection
