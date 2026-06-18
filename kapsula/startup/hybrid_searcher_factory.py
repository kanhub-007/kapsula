"""Cached HybridSearcher factory."""

from kapsula.core.application.use_cases.hybrid_searcher import HybridSearcher
from kapsula.core.domain.fusion.weighted_fusion import WeightedFusion
from kapsula.core.domain.interfaces.embedder import Embedder
from kapsula.core.domain.interfaces.fusion import Fusion
from kapsula.core.domain.interfaces.reranker import Reranker
from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.indexing import (
    load_bm25_index,
    load_faiss_index,
)
from kapsula.infrastructure.repositories.retrieval import (
    DenseRetriever,
    SparseRetriever,
)

logger = get_logger(__name__)


class HybridSearcherFactory:
    """Creates and caches HybridSearcher instances."""

    def __init__(self):
        self._cache: dict[tuple, HybridSearcher] = {}

    def create(
        self,
        faiss_index_path: str,
        bm25_index_path: str,
        embedder: Embedder,
        reranker: Reranker | None = None,
        fusion: Fusion | None = None,
    ) -> HybridSearcher:
        key = (
            faiss_index_path,
            bm25_index_path,
            id(embedder),
            id(reranker),
            id(fusion),
        )

        if key not in self._cache:
            logger.debug("Creating new HybridSearcher (cache miss)")

            faiss_index = load_faiss_index(faiss_index_path)
            bm25_index, texts = load_bm25_index(bm25_index_path)

            dense = DenseRetriever(faiss_index, texts, embedder)
            sparse = SparseRetriever(bm25_index, texts)
            fusion = fusion or WeightedFusion()

            self._cache[key] = HybridSearcher(
                dense=dense, sparse=sparse, fusion=fusion, reranker=reranker
            )
        return self._cache[key]
