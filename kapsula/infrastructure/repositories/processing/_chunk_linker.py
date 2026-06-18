"""Chunk-to-parent linking extracted from tasks.py."""

import json
import logging

from kapsula.infrastructure.data import Chunk, LibraryCard
from kapsula.infrastructure.repositories.chunking.header_matcher import match_header_to_parents

logger = logging.getLogger(__name__)

def _link_chunks_to_parents(job_id, document, parent_sections, db, processing_status):
    """Link chunks to parent sections and resolve citation library_card_ids."""
# Update progress: Linking chunks to parent sections
    processing_status[job_id] = {
        "status": "processing",
        "progress": 70,
        "stage": "linking_chunks",
        "message": "Linking chunks to parent sections...",
    }
    logger.debug(f"Job {job_id}: Linking chunks to parent sections")

    # Query all chunks for this document
    chunks_in_db = db.query(Chunk).filter(Chunk.document_id == document.id).all()

    # Track linking statistics
    link_stats = {
        "total_chunks": len(chunks_in_db),
        "chunks_with_headers": 0,
        "chunks_linked_immediate": 0,
        "chunks_linked_chapter": 0,
        "chunks_linked_page": 0,
        "chunks_no_match": 0,
    }

    # Create a mapping of library card doc_ids (hashes) to database IDs
    library_cards_map = {}
    for library_card in (
        db.query(LibraryCard).filter(LibraryCard.document_id == document.id).all()
    ):
        library_cards_map[library_card.doc_id] = library_card.id

    # Update each chunk with parent pointers and resolve citation library_card_ids
    for chunk in chunks_in_db:
        # Parse existing metadata
        metadata = json.loads(chunk.chunk_metadata)

        # Extract header from metadata
        header = metadata.get("header", "")

        # Match header to parent sections
        if header:
            link_stats["chunks_with_headers"] += 1
            parents = match_header_to_parents(header, parent_sections)
            metadata["parents"] = parents

            # Track which levels were matched
            if parents.get("immediate"):
                link_stats["chunks_linked_immediate"] += 1
            if parents.get("chapter"):
                link_stats["chunks_linked_chapter"] += 1
            if parents.get("page"):
                link_stats["chunks_linked_page"] += 1

            if not any(parents.values()):
                link_stats["chunks_no_match"] += 1
                logger.warning(
                    f"Job {job_id}: Chunk {chunk.chunk_index} with header '{header}' has NO parent matches!"
                )

            # Resolve citation library_card_id if citation exists
            citation = metadata.get("citation")
            if citation and citation.get("library_card_doc_id"):
                doc_id = citation["library_card_doc_id"]
                if doc_id in library_cards_map:
                    citation["library_card_id"] = library_cards_map[doc_id]
                    # Remove the temporary doc_id field
                    del citation["library_card_doc_id"]
                    logger.debug(
                        f"Chunk {chunk.chunk_index}: Resolved citation library_card_id={citation['library_card_id']}"
                    )
                else:
                    logger.warning(
                        f"Chunk {chunk.chunk_index}: Could not resolve library_card_doc_id '{doc_id}'"
                    )
                    citation["library_card_id"] = None
                    del citation["library_card_doc_id"]

            metadata["citation"] = citation

            # Save updated metadata back to chunk
            chunk.chunk_metadata = json.dumps(metadata)
        else:
            logger.warning(
                f"Job {job_id}: Chunk {chunk.chunk_index} has NO header in metadata"
            )

    db.commit()

    # Log comprehensive linking statistics
    logger.info(f"Job {job_id}: Parent linking complete:")
    logger.info(f"  Total chunks: {link_stats['total_chunks']}")
    logger.info(f"  Chunks with headers: {link_stats['chunks_with_headers']}")
    logger.info(
        f"  Chunks linked to immediate (H3): {link_stats['chunks_linked_immediate']}"
    )
    logger.info(
        f"  Chunks linked to chapter (H2): {link_stats['chunks_linked_chapter']}"
    )
    logger.info(f"  Chunks linked to page (H1): {link_stats['chunks_linked_page']}")
    logger.info(f"  Chunks with NO matches: {link_stats['chunks_no_match']}")

    if link_stats["chunks_no_match"] > 0:
        logger.error(
            f"Job {job_id}: {link_stats['chunks_no_match']} chunks failed to link to parents - context expansion will fail for these!"
        )



def _build_document_indexes(job_id, document, chunks, db, ingestion_mode, upload_progress):
    """Build FAISS and BM25 search indexes for a document."""
    import os
    import time
    from kapsula.infrastructure.repositories.embedding.huggingface_embedder import HuggingFaceEmbedder
    from kapsula.infrastructure.repositories.indexing import DocumentIndexBuilder
    from kapsula.infrastructure.data.connection import DATA_DIR

    index_stage_start = time.time()
    upload_progress.set(
        job_id,
        status="processing",
        progress=85,
        stage="building_indexes",
        message="Building search indexes (FAISS and BM25)...",
        ingestion_mode=ingestion_mode,
    )

    try:
        account_id = (
            document.collection.account.account_id
            if document.collection.account
            else None
        )
        collection_id = document.collection.collection_id

        embedder = HuggingFaceEmbedder(
            endpoint_url=os.getenv("EMBEDDING_MODEL_URL", "Qwen/Qwen3-Embedding-8B"),
            token=os.getenv("HF_API_TOKEN") or os.getenv("HF_TOKEN", ""),
        )
        builder = DocumentIndexBuilder(embedder, DATA_DIR)

        index_paths = builder.build(
            chunks, job_id, account_id=account_id, collection_id=collection_id
        )

        document.faiss_index_path = index_paths.faiss
        document.bm25_index_path = index_paths.bm25
        db.commit()

        import logging
        logging.getLogger(__name__).info("Job %s: Search indexes created successfully", job_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Job %s: Failed to build indexes: %s", job_id, e, exc_info=True)
    finally:
        upload_progress.log_stage(
            job_id,
            "document_indexing",
            index_stage_start,
            chunks=len(chunks),
            ingestion_mode=ingestion_mode,
        )
