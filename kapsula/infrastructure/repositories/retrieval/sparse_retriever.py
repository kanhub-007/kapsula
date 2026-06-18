"""BM25 sparse keyword retriever."""

import asyncio
from typing import Any

import numpy as np

from kapsula.core.domain.text_processing import tokenize


class SparseRetriever:
    """Retrieves results using BM25 keyword matching."""

    def __init__(self, bm25_index, texts: list[str]):
        self._index = bm25_index
        self._texts = texts

    async def retrieve(self, query: str, k: int) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._retrieve_sync, query, k)

    def _retrieve_sync(self, query: str, k: int) -> list[dict[str, Any]]:
        tokens = tokenize(query)
        scores = self._index.get_scores(tokens)
        # Use argpartition for O(n) top-k instead of O(n log n) full sort
        n = len(scores)
        if k >= n:
            top_indices = np.argsort(scores)[::-1]
        else:
            top_indices = np.argpartition(scores, -k)[-k:]
            top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

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
