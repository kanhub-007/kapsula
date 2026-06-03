"""BM25 sparse keyword retriever."""

import asyncio
from typing import List, Dict, Any

import numpy as np

from kapsula.core.domain.text_processing import tokenize


class SparseRetriever:
    """Retrieves results using BM25 keyword matching."""

    def __init__(self, bm25_index, texts: List[str]):
        self._index = bm25_index
        self._texts = texts

    async def retrieve(self, query: str, k: int) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._retrieve_sync, query, k)

    def _retrieve_sync(self, query: str, k: int) -> List[Dict[str, Any]]:
        tokens = tokenize(query)
        scores = self._index.get_scores(tokens)
        top_indices = np.argsort(scores)[::-1][:k]

        return [
            {
                "index": int(idx),
                "content": self._texts[idx],
                "original_rank": rank,
                "sparse_score": float(scores[idx]),
            }
            for rank, idx in enumerate(top_indices)
            if idx < len(self._texts)
        ]
