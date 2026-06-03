"""Batch sub-document index building for uploads."""

import json
import time
from typing import Any

from sqlalchemy.orm import Session

from doc_search.infrastructure.data import Document, LibraryCard, SubDocument
from doc_search.infrastructure.logging_config import get_logger
from doc_search.infrastructure.repositories.indexing import DocumentIndexBuilder
from doc_search.presentation.upload.upload_progress_tracker import UploadProgressTracker

logger = get_logger(__name__)


class SubDocumentBatchIndexer:
    """Build sub-document indexes using one batched embedding pass."""

    def __init__(
        self,
        builder: DocumentIndexBuilder,
        progress_tracker: UploadProgressTracker,
    ):
        self._builder = builder
        self._progress = progress_tracker

    def build(
        self,
        *,
        db: Session,
        document: Document,
        pending_subdocument_indexes: list[dict[str, Any]],
        job_id: str,
        upload_start_time: float,
        ingestion_mode: str,
    ) -> None:
        """Batch embed and build indexes for all processed sub-documents."""
        if not pending_subdocument_indexes:
            return

        batch_stage_start = time.time()
        account_id = (
            document.collection.account.account_id
            if document.collection.account
            else None
        )
        collection_id = document.collection.collection_id

        all_texts: list[str] = []
        embedding_slices: list[tuple[dict[str, Any], int, int]] = []
        for item in pending_subdocument_indexes:
            filtered = self._builder.filter_chunks(item["chunks"])
            if not filtered:
                logger.warning(
                    "Job %s: No valid chunks to index for sub-document '%s'",
                    job_id,
                    item["breadcrumb_key"],
                )
                continue
            start = len(all_texts)
            item["filtered_chunks"] = filtered
            all_texts.extend(chunk["content"] for chunk in filtered)
            embedding_slices.append((item, start, len(all_texts)))

        if not all_texts:
            logger.warning(
                "Job %s: No valid sub-document chunks to batch index", job_id
            )
            return

        self._progress.set(
            job_id,
            status="processing",
            progress=80,
            stage="final_subdocument_finishing",
            message=(
                f"Batch embedding {len(all_texts)} chunks from "
                f"{len(embedding_slices)} sub-documents "
                f"({self._progress.elapsed_message(upload_start_time)})."
            ),
            chunk_count=len(all_texts),
            subdocument_count=len(embedding_slices),
            ingestion_mode=ingestion_mode,
        )
        try:
            embeddings = self._builder.embed_texts(all_texts)
        except Exception as exc:
            logger.error(
                "Job %s: Batch embedding failed; sub-document indexes were not built: %s",
                job_id,
                exc,
                exc_info=True,
            )
            self._progress.set(
                job_id,
                status="processing",
                progress=82,
                stage="subdocument_indexing",
                message=(
                    "Batch embedding failed; continuing without sub-document "
                    "indexes to preserve upload completion."
                ),
                chunk_count=len(all_texts),
                subdocument_count=len(embedding_slices),
                ingestion_mode=ingestion_mode,
            )
            return

        self._progress.log_stage(
            job_id,
            "subdocument_embedding_batch",
            batch_stage_start,
            chunks=len(all_texts),
            subdocuments=len(embedding_slices),
            ingestion_mode=ingestion_mode,
        )

        index_stage_start = time.time()
        self._progress.set(
            job_id,
            status="processing",
            progress=82,
            stage="subdocument_indexing",
            message=(
                f"Writing indexes for {len(embedding_slices)} sub-documents "
                f"({self._progress.elapsed_message(upload_start_time)})."
            ),
            chunk_count=len(all_texts),
            subdocument_count=len(embedding_slices),
            ingestion_mode=ingestion_mode,
        )

        for item, start, end in embedding_slices:
            self._build_one(
                db=db,
                item=item,
                embeddings=embeddings[start:end],
                job_id=job_id,
                account_id=account_id,
                collection_id=collection_id,
            )

        db.commit()
        self._progress.log_stage(
            job_id,
            "subdocument_indexing",
            index_stage_start,
            chunks=len(all_texts),
            subdocuments=len(embedding_slices),
            ingestion_mode=ingestion_mode,
        )

    def _build_one(
        self,
        *,
        db: Session,
        item: dict[str, Any],
        embeddings: Any,
        job_id: str,
        account_id: str | None,
        collection_id: str | None,
    ) -> None:
        subdoc_id = item["subdoc_id"]
        breadcrumb_key = item["breadcrumb_key"]
        try:
            index_paths = self._builder.build_from_embeddings(
                item.get("filtered_chunks", item["chunks"]),
                embeddings,
                job_id=f"{job_id}_subdoc_{subdoc_id}",
                account_id=account_id,
                collection_id=collection_id,
            )

            subdoc = db.query(SubDocument).filter(SubDocument.id == subdoc_id).first()
            if not subdoc:
                logger.warning(
                    "Job %s: Sub-document %s disappeared before index path update",
                    job_id,
                    subdoc_id,
                )
                return
            subdoc.faiss_index_path = index_paths.faiss
            subdoc.bm25_index_path = index_paths.bm25
            self._update_library_card_metadata(db, subdoc_id, index_paths, job_id)

            logger.info("Job %s: Built indexes for '%s'", job_id, breadcrumb_key)
            logger.debug("  FAISS: %s", index_paths.faiss)
            logger.debug("  BM25: %s", index_paths.bm25)
        except Exception as exc:
            logger.error(
                "Job %s: Failed to build indexes for '%s': %s",
                job_id,
                breadcrumb_key,
                exc,
            )

    @staticmethod
    def _update_library_card_metadata(
        db: Session,
        subdoc_id: int,
        index_paths: Any,
        job_id: str,
    ) -> None:
        library_card = (
            db.query(LibraryCard)
            .filter(
                LibraryCard.sub_document_id == subdoc_id,
                LibraryCard.level == "subdocument",
            )
            .first()
        )
        if not library_card:
            return

        metadata = {}
        if library_card.extra_metadata:
            try:
                metadata = json.loads(library_card.extra_metadata)
            except json.JSONDecodeError:
                logger.warning(
                    "Job %s: Failed to parse sub-document card metadata for %s",
                    job_id,
                    subdoc_id,
                )
        metadata["faiss_path"] = index_paths.faiss
        metadata["bm25_path"] = index_paths.bm25
        library_card.extra_metadata = json.dumps(metadata)
