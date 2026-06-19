"""Multi-index search aggregator for Russian Doll retrieval."""

import asyncio
import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any

from kapsula.core.application.dto.collection_search import CollectionSearch
from kapsula.core.application.dto.search_result_hit import SearchResultHit
from kapsula.core.application.dto.search_scope import SearchScopeKind
from kapsula.core.application.dto.single_document_search import (
    SingleDocumentSearch,
)
from kapsula.core.application.dto.single_index_search import SingleIndexSearch
from kapsula.core.application.dto.sub_document_search import SubDocumentSearch
from kapsula.core.application.use_cases.context_expansion import (
    expand_context_with_parents,
)
from kapsula.core.application.use_cases.ranking.route_confidence_scorer import (
    RouteConfidenceScorer,
)
from kapsula.core.application.use_cases.ranking.source_quota_policy import (
    SourceQuotaPolicy,
)
from kapsula.core.application.use_cases.search_metadata_builder import (
    SearchMetadataBuilder,
)
from kapsula.core.application.use_cases.search_runtime_helpers import (
    DEFAULT_DOCUMENT_CONCURRENCY,
    gather_flattened,
    select_metadata,
)
from kapsula.core.application.use_cases.search_strategy.collection_search_strategy import (
    CollectionSearchStrategy,
)
from kapsula.core.application.use_cases.selectors.batched_sub_document_selector import (
    BatchedSubDocumentSelector,
)
from kapsula.core.application.use_cases.selectors.collection_routing_strategy import (
    make_collection_routing_strategy,
)
from kapsula.core.application.use_cases.selectors.metadata_preselector import (
    MetadataPreselector,
)
from kapsula.core.application.use_cases.selectors.sub_document_selector import (
    SubDocumentSelector,
)
from kapsula.core.domain.interfaces.chat_client import ChatClient
from kapsula.core.domain.interfaces.embedder import Embedder
from kapsula.core.domain.interfaces.reranker import Reranker
from kapsula.core.domain.interfaces.search_data_access import SearchDataAccess
from kapsula.core.domain.interfaces.searcher import Searcher

logger = logging.getLogger(__name__)


class MultiIndexSearcher:
    """Searches across sub-documents, collections, and single indexes with LLM selection."""

    def __init__(
        self,
        data: SearchDataAccess,
        embedder: Embedder,
        reranker: Reranker,
        chat_client: ChatClient,
        make_searcher: Callable[[str, str], Searcher],
        strategies: list[CollectionSearchStrategy] | None = None,
        quota_policy: SourceQuotaPolicy | None = None,
        route_scorer: RouteConfidenceScorer | None = None,
        document_concurrency: int = DEFAULT_DOCUMENT_CONCURRENCY,
    ):
        self._data = data
        self._embedder = embedder
        self._reranker = reranker
        self._chat_client = chat_client
        self._make_searcher = make_searcher
        self._metadata = SearchMetadataBuilder(data)
        self._strategies = strategies or []
        self._quota_policy = quota_policy or SourceQuotaPolicy(per_subdocument_limit=3)
        self._route_scorer = route_scorer or RouteConfidenceScorer()
        self._document_concurrency = max(1, document_concurrency)

    def _get_searcher(self, faiss_path: str, bm25_path: str) -> Searcher:
        return self._make_searcher(faiss_path, bm25_path)

    async def search_subdocuments(
        self, search: SubDocumentSearch
    ) -> list[SearchResultHit]:
        subdocs = self._data.get_sub_documents(search.document_id)
        if not subdocs:
            return []

        metadata = self._metadata.build_subdoc_metadata(subdocs)
        selector = SubDocumentSelector(self._chat_client)
        routing_started = perf_counter()
        selected = select_metadata(selector, search.query, metadata)
        routing_elapsed = perf_counter() - routing_started
        logger.info(
            "Subdocument routing completed in %.3fs: selected=%s/%s document_id=%s",
            routing_elapsed,
            len(selected),
            len(metadata),
            search.document_id,
        )
        if not selected:
            return []

        logger.info(f"Multi-index search: {len(selected)}/{len(subdocs)} sub-docs")
        per_k = search.top_k * search.per_subdoc_multiplier

        async def _search_one(sd: dict) -> list:
            # The searcher returns fresh dicts each call; we annotate them
            # in place with provenance. That ownership assumption is fine
            # here (closes L7) but is exactly why callers receive typed
            # SearchResultHit, not these dicts.
            try:
                searcher = self._get_searcher(sd["faiss_path"], sd["bm25_path"])
                results = await searcher.search(
                    query=search.query,
                    top_k=per_k,
                    node_type_filter=search.node_type_filter,
                    sub_document_id=sd["id"],
                )
                for r in results:
                    r["sub_document_id"] = sd["id"]
                    r["sub_document_key"] = sd["breadcrumb_key"]
                    r["document_id"] = search.document_id
                return results
            except Exception as e:
                logger.error(f"Failed to search sub-doc '{sd['breadcrumb_key']}': {e}")
                return []

        all_results = await gather_flattened([_search_one(s) for s in selected])
        logger.info(
            f"Aggregated {len(all_results)} candidates from {len(selected)} sub-docs"
        )
        if not all_results:
            return []

        all_results.sort(key=lambda r: r.get("score", 0), reverse=True)

        top = all_results[: search.top_k]
        if search.context_mode != "none":
            top = expand_context_with_parents(
                top, self._data, search.document_id, search.context_mode
            )
        return SearchResultHit.from_dicts(top)

    async def search_single_index(
        self, search: SingleIndexSearch
    ) -> list[SearchResultHit]:
        searcher = self._get_searcher(search.faiss_path, search.bm25_path)
        results = await searcher.search(
            query=search.query,
            top_k=search.top_k,
            node_type_filter=search.node_type_filter,
        )
        for r in results:
            r["document_id"] = search.document_id
        return SearchResultHit.from_dicts(results)

    async def search_document(
        self, search: SingleDocumentSearch
    ) -> list[SearchResultHit]:
        """Search one document, dispatching on its architecture (closes H5).

        Sub-document docs route through :meth:`search_subdocuments`; flat
        docs use the document-level FAISS+BM25 pair. This centralises the
        branch that was previously inlined in four API/MCP entry points.
        Requires a ready (completed) document with index paths when flat.
        """
        if self._data.count_sub_documents(search.document_id) > 0:
            return await self.search_subdocuments(
                SubDocumentSearch(
                    query=search.query,
                    document_id=search.document_id,
                    top_k=search.top_k,
                    context_mode=search.context_mode,
                    node_type_filter=search.node_type_filter,
                )
            )
        if not search.faiss_path or not search.bm25_path:
            raise ValueError("No search indexes available for this document.")
        return await self.search_single_index(
            SingleIndexSearch(
                query=search.query,
                faiss_path=search.faiss_path,
                bm25_path=search.bm25_path,
                document_id=search.document_id,
                top_k=search.top_k,
                context_mode=search.context_mode,
                node_type_filter=search.node_type_filter,
            )
        )

    async def search_collections(
        self, search: CollectionSearch
    ) -> list[SearchResultHit]:
        total_started = perf_counter()
        scope = search.scope
        if scope.kind == SearchScopeKind.COLLECTION:
            collection = self._data.get_collection_by_collection_id(scope.collection_id)
            collections = [collection] if collection else []
        elif scope.kind == SearchScopeKind.ACCOUNT:
            collections = self._data.get_collections_by_account(scope.account_id)
        else:
            collections = self._data.get_all_collections()
        if not collections:
            logger.info(
                "Collection search finished in %.3fs: no collections (account_id=%s, collection_id=%s)",
                perf_counter() - total_started,
                search.account_id,
                search.collection_id,
            )
            return []

        # Aggregate fast path: try each injected strategy
        for strategy in self._strategies:
            metadata = self._metadata.build_collection_metadata(collections)
            aggregate_results = await strategy.search(
                collection=metadata[0] if metadata else {},
                query=search.query,
                top_k=search.top_k,
                per_document_multiplier=search.per_document_multiplier,
                context_mode=search.context_mode,
                node_type_filter=search.node_type_filter,
            )
            if aggregate_results is not None:
                self._route_scorer.compute_weights(aggregate_results)
                aggregate_results.sort(key=lambda r: r.get("score", 0), reverse=True)
                aggregate_results = self._quota_policy.apply(
                    aggregate_results, search.top_k
                )
                logger.info(
                    "Collection search total time %.3fs: aggregate fast path returned=%s",
                    perf_counter() - total_started,
                    len(aggregate_results),
                )
                return SearchResultHit.from_dicts(aggregate_results)

        metadata = self._metadata.build_collection_metadata(collections)
        routing_started = perf_counter()
        if scope.kind == SearchScopeKind.COLLECTION:
            selected = metadata
        else:
            strategy = make_collection_routing_strategy(
                search.routing_mode, self._chat_client
            )
            selected = strategy.select(search.query, metadata)
        routing_elapsed = perf_counter() - routing_started
        if not selected:
            logger.info(
                "Collection routing completed in %.3fs: selected=0/%s",
                routing_elapsed,
                len(collections),
            )
            return []

        logger.info(
            "Collection routing completed in %.3fs: selected=%s/%s collection_id=%s account_id=%s",
            routing_elapsed,
            len(selected),
            len(collections),
            search.collection_id,
            search.account_id,
        )

        document_concurrency = self._document_concurrency
        document_semaphore = asyncio.Semaphore(document_concurrency)

        async def _search_coll(cd: dict) -> list:
            try:
                docs = self._data.get_completed_documents(cd["id"])
                if not docs:
                    return []
                collection_results = await self._search_collection_documents(
                    collection=cd,
                    docs=docs,
                    search=search,
                    document_semaphore=document_semaphore,
                )
                logger.info(
                    "Collection document searches completed: collection='%s' documents=%s candidates=%s concurrency=%s",
                    cd["name"],
                    len(docs),
                    len(collection_results),
                    document_concurrency,
                )
                return collection_results
            except Exception as e:
                logger.error(f"Failed to search collection '{cd['name']}': {e}")
                return []

        all_results = await gather_flattened([_search_coll(c) for c in selected])
        logger.info(
            "Aggregated %s candidates from %s collections in %.3fs",
            len(all_results),
            len(selected),
            perf_counter() - total_started,
        )
        if not all_results:
            return []

        self._route_scorer.compute_weights(all_results)
        all_results.sort(key=lambda r: r.get("score", 0), reverse=True)
        all_results = self._quota_policy.apply(all_results, search.top_k)

        top = all_results[: search.top_k]
        if search.context_mode != "none":
            top = self._expand_by_document(top, search.context_mode)
        logger.info(
            "Collection search total time %.3fs: searched_collections=%s returned=%s",
            perf_counter() - total_started,
            len(selected),
            len(top),
        )
        return SearchResultHit.from_dicts(top)

    async def _search_collection_documents(
        self,
        collection: dict,
        docs: list[Any],
        search: CollectionSearch,
        document_semaphore: asyncio.Semaphore,
    ) -> list:
        subdoc_candidates, single_index_docs = (
            self._metadata.collect_collection_search_targets(collection, docs)
        )
        tasks = []
        if subdoc_candidates:
            selected_subdocs = self._select_batched_subdocuments(
                search, subdoc_candidates
            )
            tasks.extend(
                self._search_subdoc_candidate(
                    candidate,
                    search,
                    document_semaphore,
                )
                for candidate in selected_subdocs
            )
        tasks.extend(
            self._search_single_document_in_collection(
                collection,
                doc,
                search,
                document_semaphore,
            )
            for doc in single_index_docs
        )
        return await gather_flattened(tasks)

    def _select_batched_subdocuments(
        self, search: CollectionSearch, candidates: list[dict]
    ) -> list[dict]:
        preselector = MetadataPreselector(
            max_candidates=search.max_subdocument_candidates_for_llm,
            min_candidates=search.min_subdocument_candidates,
        )
        preselected = preselector.select(search.query, candidates)
        routing_mode = (search.routing_mode or "auto").lower()
        if routing_mode == "fast":
            selected = preselected
        else:
            selector = BatchedSubDocumentSelector(self._chat_client)
            decisions = selector.select(search.query, preselected)
            selected = []
            for candidate in preselected:
                decision = decisions.get(candidate["id"])
                if not decision:
                    continue
                routed = dict(candidate)
                routed["subdocument_route_confidence"] = decision.confidence
                routed["subdocument_route_reason"] = decision.reason
                selected.append(routed)
            if not selected:
                selected = preselected

        for candidate in selected:
            candidate.setdefault(
                "subdocument_route_confidence",
                candidate.get("metadata_route_confidence", 0.7),
            )
        logger.info(
            "Batched subdocument routing selected %s/%s candidates after metadata preselection %s/%s",
            len(selected),
            len(candidates),
            len(preselected),
            len(candidates),
        )
        return selected

    async def _search_subdoc_candidate(
        self,
        candidate: dict,
        search: CollectionSearch,
        document_semaphore: asyncio.Semaphore,
    ) -> list:
        async with document_semaphore:
            started = perf_counter()
            try:
                searcher = self._get_searcher(
                    candidate["faiss_path"], candidate["bm25_path"]
                )
                results = await searcher.search(
                    query=search.query,
                    top_k=search.top_k * search.per_document_multiplier * 2,
                    node_type_filter=search.node_type_filter,
                    sub_document_id=candidate["id"],
                )
                for result in results:
                    self._attach_route_metadata(result, candidate)
                logger.info(
                    "Subdocument candidate search completed in %.3fs: document='%s' subdoc='%s' results=%s",
                    perf_counter() - started,
                    candidate.get("document_filename", "?"),
                    candidate.get("breadcrumb_key", "?"),
                    len(results),
                )
                return results
            except Exception as exc:
                logger.error(
                    "Failed to search sub-doc candidate '%s': %s",
                    candidate.get("breadcrumb_key", "?"),
                    exc,
                )
                return []

    async def _search_single_document_in_collection(
        self,
        collection: dict,
        doc: Any,
        search: CollectionSearch,
        document_semaphore: asyncio.Semaphore,
    ) -> list:
        async with document_semaphore:
            started = perf_counter()
            results = await self.search_single_index(
                SingleIndexSearch(
                    query=search.query,
                    faiss_path=doc.faiss_index_path,
                    bm25_path=doc.bm25_index_path,
                    document_id=doc.id,
                    top_k=search.top_k * search.per_document_multiplier,
                    context_mode="none",
                    node_type_filter=search.node_type_filter,
                )
            )
            candidate = {
                "collection_id": collection["id"],
                "collection_name": collection["name"],
                "collection_route_confidence": collection.get(
                    "collection_route_confidence", 1.0
                ),
                "document_id": doc.id,
                "document_filename": doc.filename,
                "subdocument_route_confidence": 1.0,
            }
            for result in results:
                self._attach_route_metadata(result, candidate)
            logger.info(
                "Single-index document search completed in %.3fs: collection='%s' document='%s' results=%s",
                perf_counter() - started,
                collection["name"],
                doc.filename,
                len(results),
            )
            return results

    @staticmethod
    def _attach_route_metadata(result: dict, candidate: dict) -> None:
        result.update(
            collection_id=candidate.get("collection_id"),
            collection_name=candidate.get("collection_name"),
            collection_route_confidence=candidate.get(
                "collection_route_confidence", 1.0
            ),
            document_id=candidate.get("document_id"),
            document_filename=candidate.get("document_filename"),
            sub_document_id=candidate.get("id"),
            sub_document_key=candidate.get("breadcrumb_key"),
            subdocument_route_confidence=candidate.get(
                "subdocument_route_confidence", 1.0
            ),
            metadata_route_confidence=candidate.get("metadata_route_confidence"),
        )

    def _expand_by_document(self, results: list, context_mode: str) -> list:
        by_doc: dict[int, list] = {}
        for r in results:
            by_doc.setdefault(r.get("document_id"), []).append(r)
        expanded = []
        for doc_id, doc_results in by_doc.items():
            expanded.extend(
                expand_context_with_parents(
                    doc_results, self._data, doc_id, context_mode
                )
            )
        return expanded
