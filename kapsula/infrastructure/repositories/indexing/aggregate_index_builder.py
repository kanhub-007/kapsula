"""Aggregate index builder for collection and account scopes."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
from typing import Any

import faiss
import numpy as np
from rank_bm25 import BM25Plus
from sqlalchemy.orm import Session

from kapsula.core.application.dto.aggregate_index_paths import (
    AggregateIndexPaths,
)
from kapsula.core.domain.interfaces.embedder import Embedder
from kapsula.core.domain.text_processing import tokenize
from kapsula.infrastructure.data.tables.document import Document
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class AggregateIndexBuilder:
    """Build aggregate FAISS and BM25 indexes for collections and accounts."""

    def __init__(self, embedder: Embedder, data_dir: str):
        self._embedder = embedder
        self._data_dir = data_dir

    def build(
        self,
        db: Session,
        collection_id: int,
        account_id: str | None = None,
        collection_guid: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Build collection-level aggregate indexes."""
        docs = (
            db.query(Document)
            .filter(
                Document.collection_id == collection_id,
                Document.status == "completed",
                Document.doc_state == "active",
            )
            .all()
        )
        if not docs:
            logger.info("No completed documents for collection %s", collection_id)
            return None, None

        return self._build_from_docs(
            docs,
            AggregateIndexPaths.for_collection(
                self._data_dir, account_id, collection_guid
            ),
            label=f"collection {collection_id}",
        )

    def build_account(
        self,
        db: Session,
        account_id: int,
        account_guid: str,
    ) -> tuple[str | None, str | None]:
        """Build account-level aggregate indexes."""
        from kapsula.infrastructure.data.tables.collection import Collection

        collection_ids = (
            db.query(Collection.id).filter(Collection.account_id == account_id).all()
        )
        cids = [row[0] for row in collection_ids]
        if not cids:
            logger.info("No collections for account %s", account_id)
            return None, None

        docs = (
            db.query(Document)
            .filter(
                Document.collection_id.in_(cids),
                Document.status == "completed",
                Document.doc_state == "active",
            )
            .all()
        )
        if not docs:
            logger.info("No completed documents for account %s", account_id)
            return None, None

        return self._build_from_docs(
            docs,
            AggregateIndexPaths.for_account(self._data_dir, account_guid),
            label=f"account {account_id}",
        )

    # ── shared build pipeline ─────────────────────────────────────

    def _build_from_docs(
        self,
        docs: list[Document],
        paths: AggregateIndexPaths,
        label: str,
        *,
        incremental: bool = True,
    ) -> tuple[str | None, str | None]:
        os.makedirs(paths.indexes_dir, exist_ok=True)

        existing_mapping, existing_hashes, existing_embeddings = (
            self._load_existing_aggregate_state(paths, incremental)
        )

        all_texts, all_mapping, new_texts, new_mapping = (
            self._collect_texts_and_mapping(docs, existing_hashes)
        )

        if not all_texts:
            return None, None

        new_count = len(new_texts)
        total_count = len(all_texts)
        if (
            new_count == 0
            and existing_embeddings is not None
            and len(existing_embeddings) > 0
        ):
            logger.info(
                "All %s chunks for %s already indexed; no embedding needed",
                total_count,
                label,
            )
            embeddings = existing_embeddings
        elif new_count > 0:
            logger.info(
                "Building aggregate indexes for %s: %s new chunks + %s cached = %s total from %s documents",
                label,
                new_count,
                total_count - new_count,
                total_count,
                len(docs),
            )
            new_embeddings = self._embedder.embed(new_texts)
            if existing_embeddings is not None and len(existing_embeddings) > 0:
                embeddings = np.vstack([existing_embeddings, new_embeddings])
            else:
                embeddings = new_embeddings
        else:
            logger.info(
                "Building aggregate indexes for %s: %s chunks from %s documents",
                label,
                total_count,
                len(docs),
            )
            embeddings = self._embedder.embed(all_texts)

        faiss_path = self._build_faiss_at(embeddings, paths.faiss)
        bm25_path = self._build_bm25_at(all_texts, paths.bm25)
        self._save_mapping_at(all_mapping, paths.mapping)

        if paths.faiss_npy:
            self._save_embeddings_at(embeddings, paths.faiss_npy)

        logger.info(
            "Aggregate indexes built for %s: faiss=%s bm25=%s chunks=%s new=%s",
            label,
            os.path.basename(faiss_path) if faiss_path else "none",
            os.path.basename(bm25_path) if bm25_path else "none",
            total_count,
            new_count,
        )
        return faiss_path, bm25_path

    @staticmethod
    def _collect_texts_and_mapping(
        docs: list[Document],
        existing_hashes: set[str] | None = None,
    ) -> tuple[list[str], list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        all_texts: list[str] = []
        all_mapping: list[dict[str, Any]] = []
        new_texts: list[str] = []
        new_mapping: list[dict[str, Any]] = []
        seen_hashes: set[str] = set(existing_hashes or set())
        skip_hashes = existing_hashes or set()

        for doc in docs:
            subdocs = doc.sub_documents if hasattr(doc, "sub_documents") else []
            subdocs_by_id = {sd.id: sd for sd in subdocs}

            chunks = doc.chunks if hasattr(doc, "chunks") else []
            for chunk in chunks:
                content = getattr(chunk, "content", "") or ""
                content = content.strip()
                chunk_hash = hashlib.sha256(content.encode()).hexdigest()
                if chunk_hash in seen_hashes:
                    continue
                seen_hashes.add(chunk_hash)
                if not content:
                    continue

                subdoc_id = getattr(chunk, "sub_document_id", None)
                subdoc = subdocs_by_id.get(subdoc_id) if subdoc_id else None
                entry = {
                    "chunk_hash": chunk_hash,
                    "chunk_index": getattr(chunk, "chunk_index", 0),
                    "document_id": doc.id,
                    "document_filename": doc.filename,
                    "sub_document_id": subdoc_id,
                    "sub_document_key": subdoc.breadcrumb_key if subdoc else None,
                    "collection_id": doc.collection_id,
                    "collection_name": (
                        doc.collection.name if doc.collection else None
                    ),
                }
                all_texts.append(content)
                all_mapping.append(entry)
                if chunk_hash not in skip_hashes:
                    new_texts.append(content)
                    new_mapping.append(entry)

        return all_texts, all_mapping, new_texts, new_mapping

    @staticmethod
    def _build_faiss_at(embeddings: np.ndarray, path: str) -> str:
        normalized = embeddings.astype("float32")
        faiss.normalize_L2(normalized)
        index = faiss.IndexFlatIP(normalized.shape[1])
        index.add(normalized)
        faiss.write_index(index, path)
        logger.info("Aggregate FAISS index saved: %s vectors", index.ntotal)
        return path

    @staticmethod
    def _build_bm25_at(texts: list[str], path: str) -> str:
        corpus = [tokenize(text) for text in texts]
        bm25 = BM25Plus(corpus)
        with open(path, "wb") as handle:
            pickle.dump({"bm25": bm25, "texts": texts}, handle)
        logger.info("Aggregate BM25 index saved: %s documents", len(corpus))
        return path

    @staticmethod
    def _save_mapping_at(mapping: list[dict[str, Any]], path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(mapping, handle)
        logger.info("Aggregate chunk mapping saved: %s entries", len(mapping))

    @staticmethod
    def _load_existing_aggregate_state(
        paths: AggregateIndexPaths,
        incremental: bool,
    ) -> tuple[list[dict[str, Any]], set[str], np.ndarray | None]:
        existing_mapping: list[dict[str, Any]] = []
        existing_hashes: set[str] = set()
        existing_embeddings: np.ndarray | None = None

        if not incremental:
            return existing_mapping, existing_hashes, existing_embeddings

        npy_path = paths.faiss_npy
        mapping_path = paths.mapping

        if os.path.exists(mapping_path):
            try:
                with open(mapping_path, encoding="utf-8") as handle:
                    existing_mapping = json.load(handle)
                existing_hashes = {
                    entry["chunk_hash"]
                    for entry in existing_mapping
                    if "chunk_hash" in entry
                }
                logger.debug(
                    "Loaded %s existing mapping entries with %s known hashes",
                    len(existing_mapping),
                    len(existing_hashes),
                )
            except (json.JSONDecodeError, OSError, KeyError) as exc:
                logger.warning(
                    "Failed to load existing aggregate mapping: %s; rebuilding from scratch",
                    exc,
                )
                existing_mapping = []
                existing_hashes = set()

        if os.path.exists(npy_path) and existing_hashes:
            try:
                existing_embeddings = np.load(npy_path)
                expected = len(existing_mapping)
                if len(existing_embeddings) != expected:
                    logger.warning(
                        "Embedding count mismatch: npy=%s mapping=%s; rebuilding from scratch",
                        len(existing_embeddings),
                        expected,
                    )
                    existing_embeddings = None
                    existing_hashes = set()
                    existing_mapping = []
                else:
                    logger.debug(
                        "Loaded %s cached aggregate embeddings",
                        len(existing_embeddings),
                    )
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Failed to load aggregate embeddings: %s; rebuilding from scratch",
                    exc,
                )
                existing_embeddings = None

        return existing_mapping, existing_hashes, existing_embeddings

    @staticmethod
    def _save_embeddings_at(embeddings: np.ndarray, path: str) -> None:
        np.save(path, embeddings)
        logger.info("Aggregate embeddings saved: %s vectors", len(embeddings))
