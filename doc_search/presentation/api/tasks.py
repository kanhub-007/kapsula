"""Background task functions for document processing."""

import time
import json
import os
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from doc_search.infrastructure.data import (
    Document,
    DocumentStructure,
    Chunk,
    LibraryCard,
    SubDocument,
    SubDocumentPage,
    Collection,
    DATA_DIR,
)
from doc_search.infrastructure.repositories.chunking import (
    extract_document_structure_skeleton,
    MarkdownChunker,
    extract_parent_sections,
)
from doc_search.infrastructure.repositories.chunking.breadcrumb_parser import (
    extract_subdocuments,
    generate_content_hash,
    validate_subdocuments,
)
from doc_search.infrastructure.repositories.indexing import DocumentIndexBuilder
from doc_search.infrastructure.repositories.embedding import HuggingFaceEmbedder
from doc_search.infrastructure.external.llm.chat_client import HuggingFaceChatClient
from doc_search.core.application.use_cases.collection_summary import (
    CollectionSummaryGenerator,
)
from doc_search.core.application.use_cases.upload.upload_ingestion_strategy_factory import (
    UploadIngestionStrategyFactory,
)
from doc_search.presentation.upload.upload_progress_tracker import UploadProgressTracker
from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

# Global dictionary to track processing progress
processing_status = {}
_embedder_singleton = None


_upload_progress = UploadProgressTracker(processing_status, logger)


def match_header_to_parents(header: str, parent_sections: dict) -> dict:
    """
    Match a chunk's header breadcrumb to parent section hashes.

    Args:
        header: Breadcrumb path like "API > Auth > Parameters"
        parent_sections: Dict mapping hashes to parent section data

    Returns:
        Dict with keys: immediate (H3), chapter (H2), page (H1)
        Falls back to immediate parent if chapter/page not found.

    Note: Level mapping is H1=level_1, H2=level_2, H3=level_3
    Context modes: "narrow" uses H3 (immediate), "deep" uses H2 (chapter)
    """
    # Split header into parts
    parts = [p.strip() for p in header.split(">")]

    # Initialize with None
    parents = {"immediate": None, "chapter": None, "page": None}

    # Track matches for debugging
    matched_titles = []

    # Match parts to parent sections by title (case-insensitive partial matching)
    for doc_id, section in parent_sections.items():
        title = section["title"]
        level = section["level"]

        # Check if title matches any part of the breadcrumb (case-insensitive)
        title_lower = title.lower()
        for part in parts:
            part_lower = part.lower()

            # Exact match or partial match (title contains part or part contains title)
            if (
                title_lower == part_lower
                or title_lower in part_lower
                or part_lower in title_lower
            ):
                # H3 is the most granular (immediate context for narrow mode)
                if level == "level_3":
                    parents["immediate"] = doc_id
                    matched_titles.append(f"immediate(H3)='{title}'")
                # H2 is chapter level (deep context mode)
                elif level == "level_2":
                    parents["chapter"] = doc_id
                    matched_titles.append(f"chapter(H2)='{title}'")
                # H1 is page level (broadest context)
                elif level == "level_1":
                    parents["page"] = doc_id
                    matched_titles.append(f"page(H1)='{title}'")
                break  # Found a match for this section, move to next

    # Log matches for debugging
    if matched_titles:
        logger.debug(f"Matched header '{header}' to: {', '.join(matched_titles)}")
    else:
        logger.warning(f"No parent matches found for header '{header}'")

    # Fallback hierarchy: narrow mode (immediate) <- chapter <- page
    # If immediate (H3) not found, try using chapter (H2)
    if not parents["immediate"] and parents["chapter"]:
        parents["immediate"] = parents["chapter"]
        logger.debug(
            f"No H3 immediate found for '{header}', using H2 chapter as fallback"
        )

    # If chapter (H2) not found, try using page (H1)
    if not parents["chapter"] and parents["page"]:
        parents["chapter"] = parents["page"]
        logger.debug(f"No H2 chapter found for '{header}', using H1 page as fallback")

    # If page (H1) not found, use whatever we have
    if not parents["page"]:
        if parents["chapter"]:
            parents["page"] = parents["chapter"]
        elif parents["immediate"]:
            parents["page"] = parents["immediate"]

    # Log final result
    has_any = any(v is not None for v in parents.values())
    if not has_any:
        logger.error(
            f"Failed to find ANY parent for header '{header}' - context expansion will fail!"
        )

    return parents


def add_citation_metadata_to_chunks(
    chunks: List[Dict[str, Any]],
    parent_sections: Dict[str, Dict[str, str]],
    markdown_content: str,
) -> List[Dict[str, Any]]:
    """
    Add citation triplet metadata to chunks before they're saved to database.

    For each chunk, finds the matching parent section and calculates:
    - library_card_doc_id: The doc_id (hash) of the parent section (to be resolved to library_card_id later)
    - start_char: Character position where chunk starts in the document
    - end_char: Character position where chunk ends in the document
    - section_title: Title of the parent section
    - section_level: Level of the parent section (level_1/2/3)

    Args:
        chunks: List of chunk dictionaries from MarkdownChunker
        parent_sections: Dict mapping doc_ids to section data with start_char/end_char
        markdown_content: Original markdown content

    Returns:
        List of chunk dictionaries with citation metadata added
    """
    logger.info(f"Adding citation metadata to {len(chunks)} chunks")

    for chunk_data in chunks:
        metadata = chunk_data["metadata"]
        chunk_content = chunk_data["content"]

        # Find the chunk's position in the original markdown content
        # Use the first 150 characters of chunk content for matching (more reliable)
        search_text = chunk_content[:150].strip()

        try:
            chunk_start_pos = markdown_content.find(search_text)

            if chunk_start_pos == -1:
                # Try without header if chunk has one
                if "\n\n" in chunk_content:
                    parts = chunk_content.split("\n\n", 1)
                    if len(parts) > 1:
                        search_text = parts[1][:150].strip()
                        chunk_start_pos = markdown_content.find(search_text)

            if chunk_start_pos != -1:
                chunk_end_pos = chunk_start_pos + len(chunk_content)

                # Find which parent section contains this chunk
                best_match = None
                best_match_doc_id = None

                for doc_id, section_data in parent_sections.items():
                    section_start = section_data.get("start_char", 0)
                    section_end = section_data.get("end_char", len(markdown_content))

                    # Check if chunk is within this section
                    if section_start <= chunk_start_pos < section_end:
                        # Prefer more specific matches (level_1 > level_2 > level_3)
                        level_priority = {"level_1": 3, "level_2": 2, "level_3": 1}
                        current_priority = level_priority.get(section_data["level"], 0)

                        if best_match is None or current_priority > level_priority.get(
                            best_match["level"], 0
                        ):
                            best_match = section_data
                            best_match_doc_id = doc_id

                if best_match and best_match_doc_id:
                    # Store citation metadata (library_card_id will be resolved during linking)
                    metadata["citation"] = {
                        "library_card_doc_id": best_match_doc_id,  # Hash to be resolved to ID later
                        "start_char": chunk_start_pos,
                        "end_char": chunk_end_pos,
                        "section_title": best_match["title"],
                        "section_level": best_match["level"],
                    }
                    logger.debug(
                        f"Chunk {metadata['chunk_index']}: Citation added (section='{best_match['title']}', pos={chunk_start_pos}-{chunk_end_pos})"
                    )
                else:
                    logger.warning(
                        f"Chunk {metadata['chunk_index']}: No matching parent section found"
                    )
                    metadata["citation"] = None
            else:
                logger.warning(
                    f"Chunk {metadata['chunk_index']}: Could not find chunk position in document"
                )
                metadata["citation"] = None

        except Exception as e:
            logger.error(
                f"Error adding citation to chunk {metadata.get('chunk_index', '?')}: {e}"
            )
            metadata["citation"] = None

    logger.info("Citation metadata added to all chunks")
    return chunks


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
        for chunk_data in chunks_with_citations:
            chunk = Chunk(
                document_id=document.id,
                content=chunk_data["content"],
                chunk_index=chunk_data["metadata"]["chunk_index"],
                token_count=chunk_data["token_count"],
                chunk_metadata=json.dumps(chunk_data["metadata"]),
            )
            db.add(chunk)

        db.commit()
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
        for doc_id, section_data in parent_sections.items():
            library_card = LibraryCard(
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
            db.add(library_card)

        db.commit()
        logger.debug(f"Job {job_id}: Parent sections saved to database")

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

        if ingestion_strategy.build_document_indexes:
            # Update progress: Building indexes
            index_stage_start = time.time()
            _upload_progress.set(
                job_id,
                status="processing",
                progress=85,
                stage="building_indexes",
                message="Building search indexes (FAISS and BM25)...",
                ingestion_mode=ingestion_mode,
            )
            logger.debug(f"Job {job_id}: Building search indexes")

            # Build FAISS and BM25 indexes
            try:
                # Get account_id and collection_id for organized storage
                account_id = (
                    document.collection.account.account_id
                    if document.collection.account
                    else None
                )
                collection_id = document.collection.collection_id

                embedder = HuggingFaceEmbedder(
                    endpoint_url=os.getenv(
                        "EMBEDDING_MODEL_URL", "Qwen/Qwen3-Embedding-8B"
                    ),
                    token=os.getenv("HF_API_TOKEN") or os.getenv("HF_TOKEN", ""),
                )
                builder = DocumentIndexBuilder(embedder, DATA_DIR)

                index_paths = builder.build(
                    chunks, job_id, account_id=account_id, collection_id=collection_id
                )

                # Update document with index paths
                document.faiss_index_path = index_paths.faiss
                document.bm25_index_path = index_paths.bm25
                db.commit()

                logger.info(f"Job {job_id}: Search indexes created successfully")
            except Exception as e:
                logger.error(
                    f"Job {job_id}: Failed to build indexes: {e}", exc_info=True
                )
                # Continue without indexes - not critical for completion
            finally:
                _upload_progress.log_stage(
                    job_id,
                    "document_indexing",
                    index_stage_start,
                    chunks=len(chunks),
                    ingestion_mode=ingestion_mode,
                )
        else:
            logger.info(
                "Job %s: Skipping document index build for ingestion_mode=fast",
                job_id,
            )

        # Calculate duration
        duration = time.time() - start_time
        logger.info(f"Job {job_id}: Processing completed in {duration:.2f} seconds")

        # Update document with completion status
        document.status = "completed"
        document.duration = duration

        db.commit()
        logger.debug(f"Job {job_id}: Database updated with completion status")

        if ingestion_strategy.rebuild_aggregate_indexes:
            # Step 4: Rebuild collection aggregate index
            _rebuild_collection_aggregate_index(db, document, job_id, start_time)
        else:
            _upload_progress.set(
                job_id,
                status="processing",
                progress=98,
                stage="finalizing",
                message=(
                    f"Skipping aggregate index maintenance for ingestion_mode={ingestion_mode}; "
                    "finalizing upload."
                ),
                chunk_count=len(chunks),
                duration=duration,
                ingestion_mode=ingestion_mode,
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
        logger.info(f"Job {job_id}: SUCCESS - {len(chunks)} chunks in {duration:.2f}s")

    except Exception as e:
        logger.error(
            f"Job {job_id}: Processing failed with error: {str(e)}", exc_info=True
        )

        # Update document with error status
        document = db.query(Document).filter(Document.job_id == job_id).first()
        if document:
            document.status = "failed"
            db.commit()

        # Update progress: Failed
        processing_status[job_id] = {
            "status": "failed",
            "progress": 0,
            "stage": "failed",
            "message": f"Processing failed: {str(e)}",
        }

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
        if ingestion_strategy.build_document_indexes:
            embedder = HuggingFaceEmbedder(
                endpoint_url=os.getenv(
                    "EMBEDDING_MODEL_URL", "Qwen/Qwen3-Embedding-8B"
                ),
                token=os.getenv("HF_API_TOKEN") or os.getenv("HF_TOKEN", ""),
            )
            builder = DocumentIndexBuilder(embedder, DATA_DIR)

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

            # Build indexes for this sub-document unless upload is DB-only.
            if ingestion_strategy.build_document_indexes and builder is not None:
                index_stage_start = time.time()
                try:
                    # Get account_id and collection_id for organized storage
                    account_id = (
                        document.collection.account.account_id
                        if document.collection.account
                        else None
                    )
                    collection_id = document.collection.collection_id

                    index_paths = builder.build(
                        chunks,
                        job_id=f"{job_id}_subdoc_{subdoc.id}",
                        account_id=account_id,
                        collection_id=collection_id,
                    )

                    # Update sub-document with index paths
                    subdoc.faiss_index_path = index_paths.faiss
                    subdoc.bm25_index_path = index_paths.bm25

                    logger.info(f"Job {job_id}: Built indexes for '{breadcrumb_key}'")
                    logger.debug(f"  FAISS: {index_paths.faiss}")
                    logger.debug(f"  BM25: {index_paths.bm25}")

                except Exception as e:
                    logger.error(
                        f"Job {job_id}: Failed to build indexes for '{breadcrumb_key}': {e}"
                    )
                    # Continue without indexes
                finally:
                    _upload_progress.log_stage(
                        job_id,
                        "subdocument_indexing",
                        index_stage_start,
                        subdocument=subdoc_count,
                        chunks=len(chunks),
                        ingestion_mode=ingestion_mode,
                    )
            else:
                logger.info(
                    "Job %s: Skipping indexes for sub-document '%s' because ingestion_mode=fast",
                    job_id,
                    breadcrumb_key,
                )

            # Save chunks linked to sub-document
            subdoc_link_stats = {
                "with_immediate": 0,
                "with_chapter": 0,
                "with_page": 0,
                "no_match": 0,
            }

            for chunk_data in chunks:
                # Match header to parent sections
                header = chunk_data["metadata"].get("header", "")
                parents = match_header_to_parents(header, parent_sections)

                # Update metadata with parent pointers
                chunk_data["metadata"]["parents"] = parents

                # Track linking stats
                if parents.get("immediate"):
                    subdoc_link_stats["with_immediate"] += 1
                if parents.get("chapter"):
                    subdoc_link_stats["with_chapter"] += 1
                if parents.get("page"):
                    subdoc_link_stats["with_page"] += 1
                if not any(parents.values()):
                    subdoc_link_stats["no_match"] += 1

                chunk = Chunk(
                    document_id=document.id,
                    sub_document_id=subdoc.id,
                    content=chunk_data["content"],
                    chunk_index=chunk_data["metadata"]["chunk_index"],
                    token_count=chunk_data["token_count"],
                    chunk_metadata=json.dumps(chunk_data["metadata"]),
                )
                db.add(chunk)

            logger.info(
                f"Job {job_id}: Subdoc '{breadcrumb_key}' linking stats - immediate:{subdoc_link_stats['with_immediate']}, chapter:{subdoc_link_stats['with_chapter']}, page:{subdoc_link_stats['with_page']}, no_match:{subdoc_link_stats['no_match']}"
            )

            # Create LibraryCard for sub-document
            page_titles = [p["title"] for p in pages]
            library_card = LibraryCard(
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
                    document_id=document.id,
                    sub_document_id=subdoc.id,
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

        if ingestion_strategy.update_collection_summary:
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
                update_collection_library_card(document.id, db)
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

        if ingestion_strategy.rebuild_aggregate_indexes:
            # Step 5: Rebuild collection aggregate index
            _rebuild_collection_aggregate_index(db, document, job_id, start_time)
        else:
            _upload_progress.set(
                job_id,
                status="processing",
                progress=98,
                stage="finalizing",
                message=(
                    f"Skipping collection summary and aggregate maintenance for ingestion_mode={ingestion_mode}; "
                    "finalizing upload."
                ),
                subdocument_count=len(subdocs),
                chunk_count=total_chunks,
                duration=duration,
                ingestion_mode=ingestion_mode,
                maintenance_deferred=True,
            )
            logger.info(
                "Job %s: Deferred collection summary and aggregate index maintenance for ingestion_mode=%s",
                job_id,
                ingestion_mode,
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
        logger.info(
            f"Job {job_id}: SUCCESS - {len(subdocs)} sub-documents, {total_chunks} chunks in {duration:.2f}s"
        )

    except Exception as e:
        logger.error(
            f"Job {job_id}: Russian Doll processing failed: {str(e)}", exc_info=True
        )

        # Update document with error status
        document = db.query(Document).filter(Document.job_id == job_id).first()
        if document:
            document.status = "failed"
            db.commit()

        # Update progress: Failed
        processing_status[job_id] = {
            "status": "failed",
            "progress": 0,
            "stage": "failed",
            "message": f"Russian Doll processing failed: {str(e)}",
        }

    finally:
        db.close()


def update_collection_library_card(document_id: int, db: Session):
    """
    Create or update collection library card when a document is added.

    Args:
        document_id: ID of the document that was just processed
        db: Database session
    """
    # Get document and its library card
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        logger.error(f"Document {document_id} not found")
        return

    # Get document's main library card
    doc_card = (
        db.query(LibraryCard)
        .filter(LibraryCard.document_id == document_id, LibraryCard.level == "document")
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
        db.query(LibraryCard)
        .filter(
            LibraryCard.collection_id == collection.id,
            LibraryCard.level == "collection",
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
    summary_generator = CollectionSummaryGenerator(
        HuggingFaceChatClient(
            token=os.getenv("HF_TOKEN", ""),
            model=os.getenv(
                "INTELLIGENT_SEARCH_MODEL", "deepseek-ai/DeepSeek-V3.2-Exp"
            ),
        )
    )

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

        new_card = LibraryCard(
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


def _rebuild_collection_aggregate_index(
    db: Session,
    document: Document,
    job_id: str,
    upload_start_time: float | None = None,
) -> None:
    """Rebuild collection/account aggregate indexes after a full ingestion."""
    global _embedder_singleton
    try:
        from doc_search.infrastructure.repositories.indexing.aggregate_index_builder import (
            AggregateIndexBuilder,
        )

        collection = document.collection
        if not collection:
            return

        account = collection.account
        account_guid = account.account_id if account else None

        if _embedder_singleton is None:
            from doc_search.startup import create_embedder

            _embedder_singleton = create_embedder()

        builder = AggregateIndexBuilder(_embedder_singleton, DATA_DIR)

        completed_collection_chunks = (
            db.query(Chunk)
            .join(Document, Chunk.document_id == Document.id)
            .filter(
                Document.collection_id == collection.id,
                Document.status == "completed",
            )
            .count()
        )
        collection_stage_start = time.time()
        _upload_progress.set(
            job_id,
            status="processing",
            progress=90,
            stage="collection_aggregate_index",
            message=(
                f"Rebuilding collection aggregate index: {completed_collection_chunks} chunks "
                f"from collection '{collection.name}' "
                f"({_upload_progress.elapsed_message(upload_start_time or collection_stage_start)})."
            ),
        )
        builder.build(
            db,
            collection_id=collection.id,
            account_id=account_guid,
            collection_guid=collection.collection_id,
        )
        _upload_progress.log_stage(
            job_id,
            "aggregate_collection",
            collection_stage_start,
            chunks=completed_collection_chunks,
            collection_id=collection.collection_id,
        )
        logger.info(
            "Job %s: Collection aggregate index rebuilt for collection '%s'",
            job_id,
            collection.name,
        )

        if account:
            from doc_search.infrastructure.data.tables.collection import (
                Collection as CollectionTable,
            )

            completed_account_chunks = (
                db.query(Chunk)
                .join(Document, Chunk.document_id == Document.id)
                .join(CollectionTable, Document.collection_id == CollectionTable.id)
                .filter(
                    CollectionTable.account_id == account.id,
                    Document.status == "completed",
                )
                .count()
            )
            account_stage_start = time.time()
            _upload_progress.set(
                job_id,
                status="processing",
                progress=95,
                stage="account_aggregate_index",
                message=(
                    f"Rebuilding account aggregate index: {completed_account_chunks} chunks "
                    f"for account '{account.name}' "
                    f"({_upload_progress.elapsed_message(upload_start_time or account_stage_start)})."
                ),
            )
            builder.build_account(
                db,
                account_id=account.id,
                account_guid=account.account_id,
            )
            _upload_progress.log_stage(
                job_id,
                "aggregate_account",
                account_stage_start,
                chunks=completed_account_chunks,
                account_id=account.account_id,
            )
            logger.info(
                "Job %s: Account aggregate index rebuilt for account '%s'",
                job_id,
                account.name,
            )

        _upload_progress.set(
            job_id,
            status="processing",
            progress=98,
            stage="finalizing",
            message="Aggregate maintenance finished; finalizing upload.",
        )
    except Exception as exc:
        logger.error(
            "Job %s: Failed to rebuild aggregate index: %s",
            job_id,
            exc,
        )
        _upload_progress.set(
            job_id,
            status="processing",
            progress=98,
            stage="finalizing",
            message=(
                "Aggregate maintenance failed but document indexing is complete; "
                "finalizing upload."
            ),
        )


def get_processing_status(job_id: str) -> dict:
    """
    Get the current processing status for a job.

    Args:
        job_id: Unique job identifier

    Returns:
        Dictionary with status information
    """
    return _upload_progress.get(job_id)
