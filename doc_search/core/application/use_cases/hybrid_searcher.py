"""HybridSearcher: orchestrates dense + sparse retrieval with fusion and reranking."""

import asyncio
import logging
from typing import List

from doc_search.core.domain.interfaces.retriever import Retriever
from doc_search.core.domain.interfaces.fusion import Fusion
from doc_search.core.domain.interfaces.reranker import Reranker
from doc_search.core.application.use_cases.result_filter import filter_by_node_type

logger = logging.getLogger(__name__)


class HybridSearcher:
    """Hybrid search: dense + sparse retrieval, fusion, reranking, context expansion."""

    def __init__(
        self,
        dense: Retriever,
        sparse: Retriever,
        fusion: Fusion,
        reranker: Reranker | None = None,
    ):
        self._dense = dense
        self._sparse = sparse
        self._fusion = fusion
        self._reranker = reranker

    async def search(
        self,
        query: str,
        top_k: int = 10,
        retrieval_k: int = 50,
        rerank: bool = False,
        node_type_filter: List[str] | None = None,
        sub_document_id: int | None = None,
    ) -> list[dict]:
        query = query.strip()

        dense_results, sparse_results = await asyncio.gather(
            self._dense.retrieve(query, retrieval_k),
            self._sparse.retrieve(query, retrieval_k),
        )

        fused = self._fusion.fuse(dense_results, sparse_results)

        if node_type_filter:
            fused = filter_by_node_type(fused, node_type_filter)

        if rerank and self._reranker:
            top_results = await self._reranker.rerank(query, fused[: top_k * 2], top_k)
        else:
            top_results = fused[:top_k]

        if sub_document_id is not None:
            for r in top_results:
                r["sub_document_id"] = sub_document_id

        return top_results
