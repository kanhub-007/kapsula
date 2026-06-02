"""Local cross-encoder reranker using sentence-transformers."""

import asyncio
from typing import List, Dict, Any

from doc_search.infrastructure.logging_config import get_logger

logger = get_logger(__name__)


class LocalCrossEncoderReranker:
    """Reranker backed by a local sentence-transformers CrossEncoder.

    The model is loaded lazily on first use — not at instantiation time.
    This avoids paying the model-load cost when reranking is disabled.
    """

    def __init__(self, model_name: str):
        self._model_name = model_name
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            logger.info(f"Loading local reranker model: {self._model_name}")
            self._model = CrossEncoder(self._model_name, max_length=512)

    async def rerank(
        self, query: str, candidates: List[Dict[str, Any]], top_k: int
    ) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        self._ensure_model()
        pairs = [(query, c["content"]) for c in candidates]
        scores = await asyncio.to_thread(
            self._model.predict, pairs, batch_size=16, show_progress_bar=False
        )

        for c, score in zip(candidates, scores):
            c["rerank_score"] = float(score)

        candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

        threshold = 0.2
        kept = [c for c in candidates if c.get("rerank_score", 0) >= threshold]
        logger.debug(
            f"Local reranker: kept {len(kept)}/{len(candidates)} "
            f"(threshold={threshold})"
        )
        return kept[:top_k]
