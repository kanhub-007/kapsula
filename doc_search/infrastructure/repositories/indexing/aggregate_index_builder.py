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

from doc_search.core.application.dto.aggregate_index_paths import (
    AggregateIndexPaths,
)
from doc_search.core.domain.interfaces.embedder import Embedder
from doc_search.core.domain.text_processing import tokenize
from doc_search.infrastructure.data.tables.document import Document
from doc_search.infrastructure.logging_config import get_logger

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
        from doc_search.infrastructure.data.tables.collection import Collection

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
    ) -> tuple[str | None, str | None]:
        os.makedirs(paths.indexes_dir, exist_ok=True)
        texts, mapping = self._collect_texts_and_mapping(docs)
        if not texts:
            return None, None

        logger.info(
            "Building aggregate indexes for %s: %s chunks from %s documents",
            label,
            len(texts),
            len(docs),
        )

        embeddings = self._embedder.embed(texts)
        faiss_path = self._build_faiss_at(embeddings, paths.faiss)
        bm25_path = self._build_bm25_at(texts, paths.bm25)
        self._save_mapping_at(mapping, paths.mapping)

        logger.info(
            "Aggregate indexes built for %s: faiss=%s bm25=%s chunks=%s",
            label,
            os.path.basename(faiss_path) if faiss_path else "none",
            os.path.basename(bm25_path) if bm25_path else "none",
            len(texts),
        )
        return faiss_path, bm25_path

    @staticmethod
    def _collect_texts_and_mapping(
        docs: list[Document],
    ) -> tuple[list[str], list[dict[str, Any]]]:
        texts: list[str] = []
        mapping: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()

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

                texts.append(content)
                subdoc_id = getattr(chunk, "sub_document_id", None)
                subdoc = subdocs_by_id.get(subdoc_id) if subdoc_id else None
                mapping.append(
                    {
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
                )
        return texts, mapping

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
