"""Update collection library card after document upload."""

import json
import time

from sqlalchemy.orm import Session

from kapsula.infrastructure.data.tables.collection import Collection as OrmCollection
from kapsula.infrastructure.data.tables.document import Document as OrmDocument
from kapsula.infrastructure.data.tables.library_card import LibraryCard as OrmLibraryCard
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


def update_collection_library_card(
    document_id: int, db: Session, *, summary_generator
) -> None:
    """Create or update collection library card when a document is added.

    Args:
        document_id: ID of the document that was just processed.
        db: Database session.
        summary_generator: ``CollectionSummaryGenerator`` instance (injected
            by the caller to avoid infrastructure importing from application).
    """
    # Get document and its library card
    document = db.query(OrmDocument).filter(OrmDocument.id == document_id).first()
    if not document:
        logger.error(f"Document {document_id} not found")
        return

    # Get document's main library card
    doc_card = (
        db.query(OrmLibraryCard)
        .filter(OrmLibraryCard.document_id == document_id, OrmLibraryCard.level == "document")
        .first()
    )

    if not doc_card:
        logger.warning(f"No document library card found for document {document_id}")
        return

    # Get collection
    collection = (
        db.query(Collection).filter(Collection.id == document.collection_id).first()
    )
    if not collection:
        logger.error(f"Collection {document.collection_id} not found")
        return

    # Get existing collection library card
    existing_collection_card = (
        db.query(OrmLibraryCard)
        .filter(
            OrmLibraryCard.collection_id == collection.id,
            OrmLibraryCard.level == "collection",
        )
        .first()
    )

    # Parse document metadata
    doc_metadata = {}
    if doc_card.extra_metadata:
        try:
            doc_metadata = json.loads(doc_card.extra_metadata)
        except json.JSONDecodeError:
            logger.warning(
                f"Failed to parse document library card metadata for document {document_id}"
            )

    # Initialize summary generator

    if not existing_collection_card:
        # Create new collection library card
        logger.info(
            f"Creating new collection library card for collection {collection.id}"
        )

        summary = summary_generator.generate_new_collection_summary(
            collection_name=collection.name,
            document_summary=doc_card.content,
            document_filename=document.filename,
            document_metadata=doc_metadata,
        )

        new_card = OrmLibraryCard(
            collection_id=collection.id,
            doc_id=f"collection_{collection.id}",
            level="collection",
            title=collection.name,
            content=summary,
            extra_metadata=json.dumps(
                {
                    "document_summaries": [
                        {
                            "document_id": document.id,
                            "filename": document.filename,
                            "summary": doc_card.content,
                            "subdocument_count": (
                                doc_metadata.get("sub_documents", {}).__len__()
                                if "sub_documents" in doc_metadata
                                else 0
                            ),
                            "page_count": doc_metadata.get("total_pages", 0),
                        }
                    ],
                    "total_documents": 1,
                    "total_pages": doc_metadata.get("total_pages", 0),
                    "last_updated": time.time(),
                    "generation_method": "new",
                }
            ),
        )
        db.add(new_card)
        db.commit()
        logger.info(f"✓ Created collection library card for collection {collection.id}")

    else:
        # Update existing collection library card
        logger.info(
            f"Updating existing collection library card for collection {collection.id}"
        )

        # Parse existing metadata
        existing_metadata = {}
        if existing_collection_card.extra_metadata:
            try:
                existing_metadata = json.loads(existing_collection_card.extra_metadata)
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse existing collection library card metadata"
                )
                existing_metadata = {"document_summaries": []}

        # Get existing document summaries
        existing_summaries = existing_metadata.get("document_summaries", [])

        # Generate incremental summary
        summary = summary_generator.generate_incremental_summary(
            collection_name=collection.name,
            existing_summary=existing_collection_card.content,
            existing_documents=existing_summaries,
            new_document_summary=doc_card.content,
            new_document_filename=document.filename,
            new_document_metadata=doc_metadata,
        )

        # Update metadata
        existing_summaries.append(
            {
                "document_id": document.id,
                "filename": document.filename,
                "summary": doc_card.content,
                "subdocument_count": (
                    doc_metadata.get("sub_documents", {}).__len__()
                    if "sub_documents" in doc_metadata
                    else 0
                ),
                "page_count": doc_metadata.get("total_pages", 0),
            }
        )

        existing_metadata["document_summaries"] = existing_summaries
        existing_metadata["total_documents"] = len(existing_summaries)
        existing_metadata["total_pages"] = sum(
            s.get("page_count", 0) for s in existing_summaries
        )
        existing_metadata["last_updated"] = time.time()
        existing_metadata["generation_method"] = "incremental"

        # Update card
        existing_collection_card.content = summary
        existing_collection_card.extra_metadata = json.dumps(existing_metadata)

        db.commit()
        logger.info(f"✓ Updated collection library card for collection {collection.id}")


