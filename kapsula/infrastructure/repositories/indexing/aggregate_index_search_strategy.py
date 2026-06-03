"""Aggregate index search strategy (collection and account scope)."""

from __future__ import annotations

import json
import os
from typing import Callable

from kapsula.core.application.dto.aggregate_index_paths import (
    AggregateIndexPaths,
)
from kapsula.core.application.use_cases.hybrid_searcher import HybridSearcher
from kapsula.core.domain.fusion.weighted_fusion import WeightedFusion
from kapsula.core.domain.interfaces.embedder import Embedder
from kapsula.infrastructure.logging_config import get_logger
from kapsula.infrastructure.repositories.indexing import (
    load_faiss_index,
    load_bm25_index,
)
from kapsula.infrastructure.repositories.retrieval import (
    DenseRetriever,
    SparseRetriever,
)

logger = get_logger(__name__)

PathFactory = Callable[[dict], AggregateIndexPaths | None]


class AggregateIndexSearchStrategy:
    """Search using collection-level or account-level aggregate indexes.

    The strategy is scope-agnostic — the *path_factory* callable receives
    a collection metadata dict and returns the appropriate
    ``AggregateIndexPaths`` (or ``None`` to skip).  This lets the
    composition root wire collection and account scopes from one class.
    """

    def __init__(
        self,
        data_dir: str,
        embedder: Embedder,
        path_factory: PathFactory,
    ):
        self._data_dir = data_dir
        self._embedder = embedder
        self._path_factory = path_factory

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
        paths = self._path_factory(collection)
        if paths is None or not paths.exists():
            logger.info("Aggregate index not available; falling back")
            return None

        logger.info("Using aggregate index at %s", paths.indexes_dir)

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
        logger.info(
            "Aggregate search returned %s results from %s",
            len(results),
            paths.indexes_dir,
        )
        return results

    @staticmethod
    def _decorate_with_source_metadata(
        results: list[dict],
        collection: dict,
        paths: AggregateIndexPaths,
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
