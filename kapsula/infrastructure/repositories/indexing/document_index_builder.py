"""FAISS and BM25 index builder."""

import os
import pickle
from typing import List, Dict, Any

import faiss
from rank_bm25 import BM25Plus

from kapsula.core.application.dto.index_paths import IndexPaths
from kapsula.core.domain.text_processing import tokenize, is_meaningful_chunk
from kapsula.core.domain.interfaces import Embedder
from kapsula.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class DocumentIndexBuilder:
    """Builds FAISS and BM25 indexes for a document's chunks.

    Usage::

        builder = DocumentIndexBuilder(embedder, data_dir)
        paths = builder.build(chunks, job_id)
    """

    def __init__(self, embedder: Embedder, data_dir: str):
        self._embedder = embedder
        self._data_dir = data_dir

    def build(
        self,
        chunks: List[Dict[str, Any]],
        job_id: str,
        *,
        account_id: str | None = None,
        collection_id: str | None = None,
        min_chunk_length: int = 50,
    ) -> IndexPaths:
        logger.info(f"Building indexes for document {job_id} with {len(chunks)} chunks")

        filtered = self.filter_chunks(chunks, min_chunk_length)
        if not filtered:
            raise ValueError(
                f"No valid chunks found after filtering "
                f"(min_length={min_chunk_length})"
            )

        logger.debug(f"Processing {len(filtered)} chunks after filtering")
        texts = [c["content"] for c in filtered]
        indexes_dir = self._indexes_dir(account_id, collection_id)
        embeddings = self.embed_texts(texts)

        return IndexPaths(
            faiss=self._build_faiss_from_embeddings(embeddings, job_id, indexes_dir),
            bm25=self._build_bm25(texts, job_id, indexes_dir),
        )

    def build_from_embeddings(
        self,
        chunks: List[Dict[str, Any]],
        embeddings,
        job_id: str,
        *,
        account_id: str | None = None,
        collection_id: str | None = None,
        min_chunk_length: int = 50,
    ) -> IndexPaths:
        """Build indexes from precomputed embeddings for this chunk set."""
        filtered = self.filter_chunks(chunks, min_chunk_length)
        if not filtered:
            raise ValueError(
                f"No valid chunks found after filtering "
                f"(min_length={min_chunk_length})"
            )
        if len(embeddings) != len(filtered):
            raise ValueError(
                "Embedding count does not match filtered chunk count: "
                f"embeddings={len(embeddings)} chunks={len(filtered)}"
            )

        texts = [c["content"] for c in filtered]
        indexes_dir = self._indexes_dir(account_id, collection_id)
        return IndexPaths(
            faiss=self._build_faiss_from_embeddings(embeddings, job_id, indexes_dir),
            bm25=self._build_bm25(texts, job_id, indexes_dir),
        )

    def embed_texts(self, texts: List[str]):
        """Embed texts using the configured embedder."""
        logger.info(f"Generating embeddings for {len(texts)} chunks")
        embeddings = self._embedder.embed(texts)
        logger.debug(f"Embedding generation complete. Shape: {embeddings.shape}")
        return embeddings

    def filter_chunks(
        self, chunks: List[Dict[str, Any]], min_length: int = 50
    ) -> List[Dict[str, Any]]:
        kept = [
            c
            for c in chunks
            if len(c["content"].strip()) >= min_length
            and is_meaningful_chunk(c["content"])
        ]
        dropped = len(chunks) - len(kept)
        if dropped:
            logger.warning(
                f"Filtered out {dropped} chunks shorter than "
                f"{min_length} characters"
            )
        return kept

    def _indexes_dir(self, account_id: str | None, collection_id: str | None) -> str:
        path = (
            os.path.join(
                self._data_dir,
                "indexes",
                *(p for p in (account_id, collection_id) if p),
            )
            if (account_id and collection_id)
            else os.path.join(self._data_dir, "indexes")
        )
        os.makedirs(path, exist_ok=True)
        return path

    def _build_faiss_from_embeddings(
        self, embeddings, job_id: str, indexes_dir: str
    ) -> str:
        normalized = embeddings.astype("float32")
        faiss.normalize_L2(normalized)

        index = faiss.IndexFlatIP(normalized.shape[1])
        index.add(normalized)
        logger.debug(f"Added {index.ntotal} vectors to FAISS index")

        path = os.path.join(indexes_dir, f"{job_id}_faiss.index")
        faiss.write_index(index, path)
        logger.info(f"FAISS index created at: {path}")
        return path

    def _build_bm25(self, texts: List[str], job_id: str, indexes_dir: str) -> str:
        logger.debug(f"Building BM25 index for {len(texts)} chunks")

        corpus = [tokenize(t) for t in texts]
        bm25 = BM25Plus(corpus)

        path = os.path.join(indexes_dir, f"{job_id}_bm25.pkl")
        with open(path, "wb") as f:
            pickle.dump({"bm25": bm25, "texts": texts}, f)

        logger.info(f"BM25 index created at: {path}")
        return path
