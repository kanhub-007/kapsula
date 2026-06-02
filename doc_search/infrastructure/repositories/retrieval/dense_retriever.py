"""FAISS dense vector retriever."""

import asyncio
from typing import List, Dict, Any

import faiss

from doc_search.core.domain.interfaces import Embedder


class DenseRetriever:
    """Retrieves results using FAISS vector similarity."""

    def __init__(self, faiss_index: faiss.Index, texts: List[str], embedder: Embedder):
        self._index = faiss_index
        self._texts = texts
        self._embedder = embedder

    async def retrieve(self, query: str, k: int) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._retrieve_sync, query, k)

    def _retrieve_sync(self, query: str, k: int) -> List[Dict[str, Any]]:
        q_emb = self._embedder.embed(query).astype("float32")
        faiss.normalize_L2(q_emb)

        distances, indices = self._index.search(q_emb, min(k, self._index.ntotal))

        return [
            {
                "index": int(idx),
                "content": self._texts[idx],
                "original_rank": rank,
                "dense_score": float(dist),
            }
            for rank, (idx, dist) in enumerate(zip(indices[0], distances[0]))
            if idx < len(self._texts)
        ]
