"""Background task functions for document processing."""

import json
import re
import time
from typing import Any

from sqlalchemy.orm import Session

from kapsula.core.application.use_cases.upload.upload_ingestion_strategy_factory import (
    UploadIngestionStrategyFactory,
)
from kapsula.core.domain.services.citation_linker import (
    add_citation_metadata_to_chunks,
)
from kapsula.infrastructure.data import (
    DATA_DIR,
    Chunk,
    Document,
    DocumentStructure,
    LibraryCard,
    SubDocument,
    SubDocumentPage,
)
from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.chunking import (
    MarkdownChunker,
    extract_document_structure_skeleton,
    extract_parent_sections,
)
from kapsula.infrastructure.repositories.chunking.breadcrumb_parser import (
    extract_subdocuments,
    generate_content_hash,
    validate_subdocuments,
)
from kapsula.infrastructure.repositories.chunking.header_matcher import (
    match_header_to_parents,
)
from kapsula.infrastructure.repositories.data.sql_upload_job_repository import (
    SqlUploadJobRepository,
)
from kapsula.infrastructure.repositories.indexing import DocumentIndexBuilder
from kapsula.infrastructure.repositories.processing._chunk_linker import (
    _build_document_indexes,
    _link_chunks_to_parents,
)
from kapsula.infrastructure.repositories.processing.aggregate_build_stage import (
    rebuild_collection_aggregate_index,
)
from kapsula.infrastructure.repositories.processing.collection_summary_stage import (
    update_collection_library_card,
)
from kapsula.infrastructure.repositories.processing.upload_progress_store import (
    processing_status,
)
from kapsula.infrastructure.repositories.processing.upload_progress_tracker import (
    UploadProgressTracker,
)
from kapsula.presentation.upload.sub_document_batch_indexer import (
    SubDocumentBatchIndexer,
)
from kapsula.startup import (
    create_collection_summary_generator,
    create_embedder,
    create_maintenance_state_manager,
)

logger = get_logger(__name__)

# Shared maintenance-state manager (closes A3 — no more inline construction).
_maintenance_state = create_maintenance_state_manager()

# Regex to strip image markdown (![alt](url)) and leading Figure labels from
# structural library card content so previews show real text, not image noise.
_IMG_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_FIG_LABEL_RE = re.compile(r"^\s*fig(?:ure)?\s*\d*[:.]?\s*", re.IGNORECASE)


def _strip_section_images(content: str) -> str:
    """Remove image markdown and leading Figure labels from section content.

    Structural library cards store section text for previews and browsing.
    Substack avatars/figures dominate the first ~200 chars otherwise, hiding
    the actual section content. The search index (chunks) is unaffected —
    the chunker already strips images. This only cleans the card `content`.
    """
    if not content:
        return content
    cleaned = _IMG_MD_RE.sub("", content)
    cleaned = _FIG_LABEL_RE.sub("", cleaned, count=1)
    return cleaned.lstrip()


# Live progress store lives in infrastructure; re-exported here for the
# legacy ``get_processing_status`` API used by routes/MCP tools.
_upload_progress = UploadProgressTracker(processing_status, logger)
_upload_job_manager = SqlUploadJobRepository()


# ── document-processing helpers (extracted from the orchestrators) ─────
# Each helper is one bounded phase, keeping process_document* readable.


def _persist_chunks(
    db: Session, document_id: int, chunks_with_citations: list[dict]
) -> None:
    """Insert chunk rows for a document and commit."""
    for chunk_data in chunks_with_citations:
        db.add(
            Chunk(
                document_id=document_id,
                content=chunk_data["content"],
                chunk_index=chunk_data["metadata"]["chunk_index"],
                token_count=chunk_data["token_count"],
                chunk_metadata=json.dumps(chunk_data["metadata"]),
            )
        )
    db.commit()


def _persist_parent_cards(
    db: Session, document: Document, parent_sections: dict
) -> None:
    """Insert one LibraryCard per parent section and commit."""
    for doc_id, section_data in parent_sections.items():
        db.add(
            LibraryCard(
                collection_id=document.collection_id,
                document_id=document.id,
                doc_id=doc_id,
                level=section_data["level"],
                title=section_data["title"],
                content=section_data["content"],
                extra_metadata=json.dumps(
                    {
                        "extraction_time": time.time(),
                        "start_char": section_data.get("start_char", 0),
                        "end_char": section_data.get("end_char", 0),
                    }
                ),
            )
        )
    db.commit()


def _mark_job_failed(job_id: str, message: str, db: Session) -> None:
    """Mark the document failed in DB, in live progress, and in the job table."""
    logger.exception(message)
    document = db.query(Document).filter(Document.job_id == job_id).first()
    if document:
        document.status = "failed"
        db.commit()
    processing_status[job_id] = {
        "status": "failed",
        "progress": 0,
        "stage": "failed",
        "message": message,
    }
    _upload_job_manager.update(
        job_id,
        status="failed",
        progress=0,
        stage="failed",
        error=message,
    )


def _link_and_persist_subdoc_chunks(
    db: Session,
    document: Document,
    subdoc: SubDocument,
    chunks: list[dict],
    parent_sections: dict,
) -> dict:
    """Match each chunk header to parents, persist chunk rows, return link stats."""
    stats = {
        "with_immediate": 0,
        "with_chapter": 0,
        "with_page": 0,
        "no_match": 0,
    }
    for chunk_data in chunks:
        header = chunk_data["metadata"].get("header", "")
        parents = match_header_to_parents(header, parent_sections)
        chunk_data["metadata"]["parents"] = parents

        if parents.get("immediate"):
            stats["with_immediate"] += 1
        if parents.get("chapter"):
            stats["with_chapter"] += 1
        if parents.get("page"):
            stats["with_page"] += 1
        if not any(parents.values()):
            stats["no_match"] += 1

        db.add(
            Chunk(
                document_id=document.id,
                sub_document_id=subdoc.id,
                content=chunk_data["content"],
                chunk_index=chunk_data["metadata"]["chunk_index"],
                token_count=chunk_data["token_count"],
                chunk_metadata=json.dumps(chunk_data["metadata"]),
            )
        )
    return stats


def _run_ingestion_maintenance_tail(
    *,
    db,
    document,
    job_id: str,
    chunk_count: int,
    duration: float,
    ingestion_mode: str,
    ingestion_strategy,
    upload_progress,
    start_time: float,
    summary: bool = False,
    subdocument_count: int | None = None,
) -> None:
    """Run the maintenance tail for an upload (closes P1/P3 duplication).

    Previously this ~30-line block was duplicated verbatim in both
    ``process_document`` and ``process_document_with_subdocuments``.
    Now both call this single helper. Decides rebuild-vs-stale internally.
    """
    if ingestion_strategy.rebuild_aggregate_indexes:
        embedder = create_embedder()
        rebuild_collection_aggregate_index(
            db,
            document,
            job_id,
            upload_progress=upload_progress,
            embedder=embedder,
            upload_start_time=start_time,
        )
    else:
        _maintenance_state.mark_collection_stale(
            document.collection,
            summary=summary,
            collection_index=True,
            account_index=True,
        )
        if document.collection:
            _maintenance_state.increment_uploads(document.collection.collection_id)
        extra: dict = {
            "chunk_count": chunk_count,
            "duration": duration,
            "ingestion_mode": ingestion_mode,
            "maintenance_deferred": True,
        }
        if subdocument_count is not None:
            extra["subdocument_count"] = subdocument_count
        skip_summary = "collection summary and " if summary else ""
        upload_progress.set(
            job_id,
            status="processing",
            progress=98,
            stage="finalizing",
            message=(
                f"Skipping {skip_summary}aggregate maintenance for "
                f"ingestion_mode={ingestion_mode}; finalizing upload."
            ),
            **extra,
        )
        skip_summary = "collection summary and " if summary else ""
        logger.info(
            "Job %s: Deferred %smaintenance for ingestion_mode=%s",
            job_id,
            skip_summary,
            ingestion_mode,
        )


def process_document(
    job_id: str,
    markdown_content: str,
    max_tokens: int,
    db: Session,
    ingestion_mode: str = "indexed",
):
    """
    Background task to process document.

    Args:
        job_id: Unique job identifier (GUID)
        markdown_content: Markdown content to process
        max_tokens: Maximum tokens per chunk
        db: Database session
    """
    ingestion_strategy = UploadIngestionStrategyFactory.create(ingestion_mode)
    ingestion_mode = ingestion_strategy.mode
    logger.info(
        "Starting background processing for job %s ingestion_mode=%s",
        job_id,
        ingestion_mode,
    )
    start_time = time.time()

    try:
        # Update progress: Extracting structure
        processing_status[job_id] = {
            "status": "processing",
            "progress": 10,
            "stage": "extracting_structure",
            "message": "Extracting document structure...",
        }
        logger.debug(f"Job {job_id}: Extracting structure")

        # Extract document structure (skeleton format)
        skeleton_structure = extract_document_structure_skeleton(markdown_content)
        logger.info(f"Job {job_id}: Skeleton structure extracted")

        # Get document from database
        document = db.query(Document).filter(Document.job_id == job_id).first()
        if not document:
            raise ValueError(f"Document with job_id {job_id} not found")

        # Save structure to database
        doc_structure = DocumentStructure(
            document_id=document.id, skeleton_structure=skeleton_structure
        )
        db.add(doc_structure)
        db.commit()

        # Update progress: Extracting parent sections
        processing_status[job_id] = {
            "status": "processing",
            "progress": 20,
            "stage": "extracting_parents",
            "message": "Extracting parent sections (H1, H2, H3)...",
        }
        logger.debug(f"Job {job_id}: Extracting parent sections")

        # Extract parent sections
        parent_sections = extract_parent_sections(markdown_content)
        logger.info(f"Job {job_id}: Extracted {len(parent_sections)} parent sections")
        if len(parent_sections) > 0:
            # Log sample of extracted sections
            sample_sections = list(parent_sections.items())[:3]
            for doc_id, section in sample_sections:
                logger.debug(
                    f"  Sample parent: {section['level']} - '{section['title']}' ({len(section['content'])} chars)"
                )
        else:
            logger.warning(
                f"Job {job_id}: No parent sections found! Document may have no H1/H2/H3 headings."
            )

        # Update progress: Structure extracted
        processing_status[job_id] = {
            "status": "processing",
            "progress": 30,
            "stage": "chunking",
            "message": "Creating chunks...",
        }

        # Chunk the document
        logger.debug(f"Job {job_id}: Starting chunking")
        chunks = MarkdownChunker(max_tokens=max_tokens).chunk(markdown_content)
        logger.info(f"Job {job_id}: Created {len(chunks)} chunks")

        # Add citation metadata to chunks BEFORE saving
        logger.debug(f"Job {job_id}: Adding citation metadata to chunks")
        chunks_with_citations = add_citation_metadata_to_chunks(
            chunks=chunks,
            parent_sections=parent_sections,
            markdown_content=markdown_content,
        )
        logger.info(f"Job {job_id}: Added citation metadata to chunks")

        # Update progress: Saving chunks
        processing_status[job_id] = {
            "status": "processing",
            "progress": 60,
            "stage": "saving_chunks",
            "message": f"Saving {len(chunks_with_citations)} chunks to database...",
        }
        logger.debug(
            f"Job {job_id}: Saving {len(chunks_with_citations)} chunks to database"
        )

        # Save chunks to database
        _persist_chunks(db, document.id, chunks_with_citations)
        logger.debug(f"Job {job_id}: Chunks saved to database")

        # Update progress: Saving parent sections
        processing_status[job_id] = {
            "status": "processing",
            "progress": 65,
            "stage": "saving_parents",
            "message": f"Saving {len(parent_sections)} parent sections to database...",
        }
        logger.debug(f"Job {job_id}: Saving parent sections to database")

        # Save parent sections to database
        _persist_parent_cards(db, document, parent_sections)
        logger.debug(f"Job {job_id}: Parent sections saved to database")

        _link_chunks_to_parents(
            job_id, document, parent_sections, db, processing_status
        )

        if ingestion_strategy.build_document_indexes:
            _build_document_indexes(
                job_id, document, chunks, db, ingestion_mode, _upload_progress
            )

        # Calculate duration
        duration = time.time() - start_time
        logger.info(f"Job {job_id}: Processing completed in {duration:.2f} seconds")

        # Update document with completion status
        document.status = "completed"
        document.duration = duration

        db.commit()
        logger.debug(f"Job {job_id}: Database updated with completion status")

        _run_ingestion_maintenance_tail(
            db=db,
            document=document,
            job_id=job_id,
            chunk_count=len(chunks),
            duration=duration,
            ingestion_mode=ingestion_mode,
            ingestion_strategy=ingestion_strategy,
            upload_progress=_upload_progress,
            start_time=start_time,
            summary=False,
        )

        # Update progress: Completed
        _upload_progress.set(
            job_id,
            status="completed",
            progress=100,
            stage="completed",
            message=f"Processing completed successfully. Created {len(chunks)} chunks in {duration:.2f} seconds.",
            chunk_count=len(chunks),
            duration=duration,
            ingestion_mode=ingestion_mode,
        )
        _upload_job_manager.update(
            job_id,
            status="completed",
            progress=100,
            stage="completed",
            chunk_count=len(chunks),
            duration=duration,
        )
        logger.info(f"Job {job_id}: SUCCESS - {len(chunks)} chunks in {duration:.2f}s")

    except Exception as e:
        _mark_job_failed(job_id, f"Job {job_id}: Processing failed: {e}", db)

    finally:
        db.close()


def process_document_with_subdocuments(
    job_id: str,
    markdown_content: str,
    max_tokens: int,
    db: Session,
    ingestion_mode: str = "indexed",
):
    """
    Process document with breadcrumb-based sub-document architecture.

    Args:
        job_id: Unique job identifier (GUID)
        markdown_content: Markdown content to process
        max_tokens: Maximum tokens per chunk
        db: Database session
    """
    ingestion_strategy = UploadIngestionStrategyFactory.create(ingestion_mode)
    ingestion_mode = ingestion_strategy.mode
    logger.info(
        "Starting Russian Doll multi-index processing for job %s ingestion_mode=%s",
        job_id,
        ingestion_mode,
    )
    start_time = time.time()

    try:
        # Update progress
        _upload_progress.set(
            job_id,
            status="processing",
            progress=5,
            stage="parsing_breadcrumbs",
            message="Parsing document breadcrumbs...",
            ingestion_mode=ingestion_mode,
        )

        # Get document from database
        document = db.query(Document).filter(Document.job_id == job_id).first()
        if not document:
            raise ValueError(f"Document with job_id {job_id} not found")

        # Step 1: Extract sub-documents from breadcrumb structure
        logger.info(f"Job {job_id}: Extracting sub-documents from breadcrumbs")
        subdocs = extract_subdocuments(markdown_content)

        if not validate_subdocuments(subdocs):
            logger.warning(
                f"Job {job_id}: No valid sub-documents found, falling back to legacy processing"
            )
            return process_document(
                job_id, markdown_content, max_tokens, db, ingestion_mode=ingestion_mode
            )

        logger.info(f"Job {job_id}: Found {len(subdocs)} sub-documents")

        # Update progress
        _upload_progress.set(
            job_id,
            status="processing",
            progress=10,
            stage="processing_subdocuments",
            message=f"Processing {len(subdocs)} sub-documents...",
            ingestion_mode=ingestion_mode,
        )

        # Step 2: Process each sub-document
        total_chunks = 0
        subdoc_count = 0

        builder = None
        embedder = None
        if ingestion_strategy.build_document_indexes:
            embedder = create_embedder()
            builder = DocumentIndexBuilder(embedder, DATA_DIR)

        pending_subdocument_indexes: list[dict[str, Any]] = []

        for breadcrumb_key, pages in subdocs.items():
            subdoc_count += 1
            progress = 10 + int((subdoc_count / len(subdocs)) * 70)  # 10-80%

            logger.info(
                f"Job {job_id}: Processing sub-document '{breadcrumb_key}' ({len(pages)} pages)"
            )

            subdoc_stage_start = time.time()
            _upload_progress.set(
                job_id,
                status="processing",
                progress=progress,
                stage="processing_subdocuments",
                message=(
                    f"Processing sub-document {subdoc_count}/{len(subdocs)}: "
                    f"'{breadcrumb_key}' ({_upload_progress.elapsed_message(start_time)})"
                ),
                ingestion_mode=ingestion_mode,
            )

            # Create sub-document record
            subdoc = SubDocument(
                document_id=document.id,
                breadcrumb_key=breadcrumb_key,
                breadcrumb_level=2,
                page_count=len(pages),
            )
            db.add(subdoc)
            db.flush()

            logger.debug(
                f"Job {job_id}: Created SubDocument record {subdoc.id} for '{breadcrumb_key}'"
            )

            # Save pages to sub_document_pages table
            for page in pages:
                page_record = SubDocumentPage(
                    sub_document_id=subdoc.id,
                    page_title=page["title"],
                    breadcrumb_full=page["breadcrumb"],
                    content_hash=generate_content_hash(page["content"]),
                )
                db.add(page_record)

            # Combine pages into sub-document content
            subdoc_content = "\n\n".join(page["content"] for page in pages)

            # Extract parent sections from sub-document content
            parent_sections = extract_parent_sections(subdoc_content)
            logger.info(
                f"Job {job_id}: Extracted {len(parent_sections)} parent sections from '{breadcrumb_key}'"
            )

            # Chunk sub-document
            chunks = MarkdownChunker(max_tokens=max_tokens).chunk(subdoc_content)
            logger.info(
                f"Job {job_id}: Created {len(chunks)} chunks for '{breadcrumb_key}'"
            )

            # Add citation metadata to chunks
            chunks = add_citation_metadata_to_chunks(
                chunks=chunks,
                parent_sections=parent_sections,
                markdown_content=subdoc_content,
            )
            logger.debug(
                f"Job {job_id}: Added citation metadata to chunks for '{breadcrumb_key}'"
            )

            total_chunks += len(chunks)

            # Defer sub-document indexing until all chunks are known so upload
            # can batch embeddings across sub-documents in one logical pass.
            if ingestion_strategy.build_document_indexes and builder is not None:
                pending_subdocument_indexes.append(
                    {
                        "subdoc_id": subdoc.id,
                        "subdoc_count": subdoc_count,
                        "breadcrumb_key": breadcrumb_key,
                        "chunks": chunks,
                    }
                )
            else:
                logger.info(
                    "Job %s: Skipping indexes for sub-document '%s' because ingestion_mode=fast",
                    job_id,
                    breadcrumb_key,
                )

            # Save chunks linked to sub-document
            subdoc_link_stats = _link_and_persist_subdoc_chunks(
                db, document, subdoc, chunks, parent_sections
            )

            logger.info(
                f"Job {job_id}: Subdoc '{breadcrumb_key}' linking stats - immediate:{subdoc_link_stats['with_immediate']}, chapter:{subdoc_link_stats['with_chapter']}, page:{subdoc_link_stats['with_page']}, no_match:{subdoc_link_stats['no_match']}"
            )

            # Create LibraryCard for sub-document
            page_titles = [p["title"] for p in pages]
            library_card = LibraryCard(
                collection_id=document.collection_id,
                document_id=document.id,
                sub_document_id=subdoc.id,
                doc_id=f"subdoc_{subdoc.id}",
                level="subdocument",
                title=breadcrumb_key,
                content=f"Contains {len(pages)} pages: {', '.join(page_titles[:5])}{'...' if len(page_titles) > 5 else ''}",
                extra_metadata=json.dumps(
                    {
                        "page_titles": page_titles,
                        "faiss_path": subdoc.faiss_index_path,
                        "bm25_path": subdoc.bm25_index_path,
                        "extraction_time": time.time(),
                    }
                ),
            )
            db.add(library_card)

            # Save parent sections to library cards
            for doc_id, section_data in parent_sections.items():
                parent_card = LibraryCard(
                    collection_id=document.collection_id,
                    document_id=document.id,
                    sub_document_id=subdoc.id,
                    doc_id=doc_id,
                    level=section_data["level"],
                    title=section_data["title"],
                    content=_strip_section_images(section_data["content"]),
                    extra_metadata=json.dumps(
                        {
                            "extraction_time": time.time(),
                            "start_char": section_data.get("start_char", 0),
                            "end_char": section_data.get("end_char", 0),
                        }
                    ),
                )
                db.add(parent_card)

            db.commit()

            # Resolve citation library_card_ids now that library cards are saved
            library_cards_map = {}
            for library_card in (
                db.query(LibraryCard)
                .filter(
                    LibraryCard.sub_document_id == subdoc.id,
                    LibraryCard.level.in_(["level_1", "level_2", "level_3"]),
                )
                .all()
            ):
                library_cards_map[library_card.doc_id] = library_card.id

            # Update chunks with resolved library_card_ids
            subdoc_chunks = (
                db.query(Chunk).filter(Chunk.sub_document_id == subdoc.id).all()
            )
            for chunk in subdoc_chunks:
                metadata = json.loads(chunk.chunk_metadata)
                citation = metadata.get("citation")

                if citation and citation.get("library_card_doc_id"):
                    doc_id = citation["library_card_doc_id"]
                    if doc_id in library_cards_map:
                        citation["library_card_id"] = library_cards_map[doc_id]
                        del citation["library_card_doc_id"]
                        chunk.chunk_metadata = json.dumps(metadata)
                    else:
                        logger.warning(
                            f"Could not resolve library_card_doc_id '{doc_id}' for chunk {chunk.chunk_index}"
                        )

            db.commit()
            _upload_progress.log_stage(
                job_id,
                "subdocument_processing",
                subdoc_stage_start,
                subdocument=subdoc_count,
                chunks=len(chunks),
                ingestion_mode=ingestion_mode,
            )
            logger.info(f"Job {job_id}: Completed processing '{breadcrumb_key}'")

        if ingestion_strategy.build_document_indexes and builder is not None:
            SubDocumentBatchIndexer(builder, _upload_progress).build(
                db=db,
                document=document,
                pending_subdocument_indexes=pending_subdocument_indexes,
                job_id=job_id,
                upload_start_time=start_time,
                ingestion_mode=ingestion_mode,
            )

        # Step 3: Create main document LibraryCard
        document_card_stage_start = time.time()
        _upload_progress.set(
            job_id,
            status="processing",
            progress=83,
            stage="document_card",
            message=(
                f"Creating document library card after {len(subdocs)} sub-documents "
                f"and {total_chunks} chunks ({_upload_progress.elapsed_message(start_time)})."
            ),
            subdocument_count=len(subdocs),
            chunk_count=total_chunks,
            ingestion_mode=ingestion_mode,
        )
        logger.info(f"Job {job_id}: Creating main document LibraryCard")

        subdoc_summary = {key: len(pages) for key, pages in subdocs.items()}
        main_card = LibraryCard(
            collection_id=document.collection_id,
            document_id=document.id,
            doc_id=f"main_{document.id}",
            level="document",
            title="Document Overview",
            content=f"Contains {len(subdocs)} sub-documents with {sum(subdoc_summary.values())} total pages",
            extra_metadata=json.dumps(
                {
                    "sub_documents": subdoc_summary,
                    "total_pages": sum(subdoc_summary.values()),
                    "total_chunks": total_chunks,
                    "extraction_time": time.time(),
                }
            ),
        )
        db.add(main_card)

        # Calculate duration
        duration = time.time() - start_time
        logger.info(
            f"Job {job_id}: Russian Doll processing completed in {duration:.2f} seconds"
        )

        # Update document with completion status
        document.status = "completed"
        document.duration = duration

        db.commit()
        _upload_progress.log_stage(
            job_id,
            "document_card",
            document_card_stage_start,
            subdocuments=len(subdocs),
            chunks=total_chunks,
            ingestion_mode=ingestion_mode,
        )

        if ingestion_strategy.mode == "full":
            # Step 4: Update collection library card
            summary_stage_start = time.time()
            _upload_progress.set(
                job_id,
                status="processing",
                progress=86,
                stage="collection_summary",
                message=(
                    f"Updating collection summary ({_upload_progress.elapsed_message(start_time)})."
                ),
                subdocument_count=len(subdocs),
                chunk_count=total_chunks,
                duration=duration,
                ingestion_mode=ingestion_mode,
            )
            logger.info(f"Job {job_id}: Updating collection library card")
            try:
                summary_generator = create_collection_summary_generator()
                update_collection_library_card(
                    document.id, db, summary_generator=summary_generator
                )
            except Exception as e:
                logger.error(
                    f"Job {job_id}: Failed to update collection library card: {e}"
                )
            finally:
                _upload_progress.log_stage(
                    job_id,
                    "collection_summary",
                    summary_stage_start,
                    ingestion_mode=ingestion_mode,
                )

        _run_ingestion_maintenance_tail(
            db=db,
            document=document,
            job_id=job_id,
            chunk_count=total_chunks,
            duration=duration,
            ingestion_mode=ingestion_mode,
            ingestion_strategy=ingestion_strategy,
            upload_progress=_upload_progress,
            start_time=start_time,
            summary=True,
            subdocument_count=len(subdocs),
        )

        # Update progress: Completed
        _upload_progress.set(
            job_id,
            status="completed",
            progress=100,
            stage="completed",
            message=f"Russian Doll processing completed. Created {len(subdocs)} sub-documents with {total_chunks} total chunks in {duration:.2f}s.",
            subdocument_count=len(subdocs),
            chunk_count=total_chunks,
            duration=duration,
            ingestion_mode=ingestion_mode,
        )
        _upload_job_manager.update(
            job_id,
            status="completed",
            progress=100,
            stage="completed",
            chunk_count=total_chunks,
            subdocument_count=len(subdocs),
            duration=duration,
        )
        logger.info(
            f"Job {job_id}: SUCCESS - {len(subdocs)} sub-documents, {total_chunks} chunks in {duration:.2f}s"
        )

    except Exception as e:
        _mark_job_failed(
            job_id, f"Job {job_id}: Russian Doll processing failed: {e}", db
        )

    finally:
        db.close()


def get_processing_status(job_id: str) -> dict:
    """Return the current processing status for a job.

    Args:
        job_id: Unique job identifier.

    Returns:
        Dictionary with status information, or None if not found.
    """
    return _upload_progress.get(job_id)
