"""Account-level aggregate search strategy."""

from __future__ import annotations

import json
import os

from doc_search.core.application.dto.account_index_paths import (
    AccountIndexPaths,
)
from doc_search.core.application.use_cases.hybrid_searcher import HybridSearcher
from doc_search.core.domain.fusion.weighted_fusion import WeightedFusion
from doc_search.core.domain.interfaces.embedder import Embedder
from doc_search.infrastructure.logging_config import get_logger
from doc_search.infrastructure.repositories.indexing import (
    load_faiss_index,
    load_bm25_index,
)
from doc_search.infrastructure.repositories.retrieval import (
    DenseRetriever,
    SparseRetriever,
)

logger = get_logger(__name__)


class AccountIndexSearchStrategy:
    """Search an account using its aggregate FAISS and BM25 indexes."""

    def __init__(self, data_dir: str, embedder: Embedder):
        self._data_dir = data_dir
        self._embedder = embedder

    async def search(
        self,
        collection: dict,
        query: str,
        top_k: int,
        per_document_multiplier: int,
        rerank: bool,
        context_mode: str,
        node_type_filter: list[str] | None,
    ) -> list[dict] | None:
        account_guid = collection.get("account_guid")
        if not account_guid:
            return None

        paths = AccountIndexPaths.from_parts(self._data_dir, account_guid)
        if not paths.exists():
            logger.info("No account aggregate index; falling back")
            return None

        logger.info("Using account aggregate index")

        faiss_index = load_faiss_index(paths.faiss)
        bm25_data = load_bm25_index(paths.bm25)
        bm25_index = bm25_data[0] if isinstance(bm25_data, tuple) else bm25_data
        texts = bm25_data[1] if isinstance(bm25_data, tuple) else bm25_data

        searcher = HybridSearcher(
            dense=DenseRetriever(faiss_index, texts, self._embedder),
            sparse=SparseRetriever(bm25_index, texts),
            fusion=WeightedFusion(),
            reranker=None,
        )

        results = await searcher.search(
            query=query,
            top_k=top_k * per_document_multiplier * 2,
            rerank=False,
            node_type_filter=node_type_filter,
        )

        self._decorate_with_source_metadata(results, collection, paths)
        logger.info("Account aggregate search returned %s results", len(results))
        return results

    @staticmethod
    def _decorate_with_source_metadata(
        results: list[dict],
        collection: dict,
        paths: AccountIndexPaths,
    ) -> None:
        if not os.path.exists(paths.mapping):
            return
        with open(paths.mapping, "r", encoding="utf-8") as handle:
            mapping: list[dict] = json.load(handle)

        for result in results:
            idx = result.get("index", -1)
            if 0 <= idx < len(mapping):
                source = mapping[idx]
                result.update(
                    collection_id=source.get("collection_id"),
                    collection_name=source.get("collection_name"),
                    collection_route_confidence=collection.get(
                        "collection_route_confidence", 1.0
                    ),
                    document_id=source.get("document_id"),
                    document_filename=source.get("document_filename"),
                    sub_document_id=source.get("sub_document_id"),
                    sub_document_key=source.get("sub_document_key"),
                    subdocument_route_confidence=1.0,
                )
