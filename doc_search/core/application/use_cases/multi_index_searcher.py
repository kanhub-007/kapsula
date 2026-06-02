"""Multi-index search aggregator for Russian Doll retrieval."""

import asyncio
import json
import logging
import os
from time import perf_counter
from typing import Callable
from typing import List, Dict, Any

from doc_search.core.application.dto.collection_search import CollectionSearch
from doc_search.core.application.dto.search_scope import SearchScopeKind
from doc_search.core.application.dto.single_index_search import SingleIndexSearch
from doc_search.core.application.dto.sub_document_search import SubDocumentSearch
from doc_search.core.application.use_cases.context_expansion import (
    expand_context_with_parents,
)
from doc_search.core.application.use_cases.selectors.routing_strategy import (
    make_collection_routing_strategy,
)
from doc_search.core.application.use_cases.selectors.sub_document_selector import (
    SubDocumentSelector,
)
from doc_search.core.domain.interfaces.chat_client import ChatClient
from doc_search.core.domain.interfaces.embedder import Embedder
from doc_search.core.domain.interfaces.reranker import Reranker
from doc_search.core.domain.interfaces.search_data_access import SearchDataAccess

logger = logging.getLogger(__name__)


class MultiIndexSearcher:
    """Searches across sub-documents, collections, and single indexes with LLM selection."""

    def __init__(
        self,
        data: SearchDataAccess,
        embedder: Embedder,
        reranker: Reranker,
        chat_client: ChatClient,
        make_searcher: Callable,
    ):
        self._data = data
        self._embedder = embedder
        self._reranker = reranker
        self._chat_client = chat_client
        self._make_searcher = make_searcher

    def _get_searcher(self, faiss_path: str, bm25_path: str):
        return self._make_searcher(faiss_path, bm25_path)

    async def search_subdocuments(
        self, search: SubDocumentSearch
    ) -> List[Dict[str, Any]]:
        subdocs = self._data.get_sub_documents(search.document_id)
        if not subdocs:
            return []

        metadata = self._build_subdoc_metadata(subdocs)
        selector = SubDocumentSelector(self._chat_client)
        routing_started = perf_counter()
        selected = _select(selector, search.query, metadata)
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
            try:
                searcher = self._get_searcher(sd["faiss_path"], sd["bm25_path"])
                results = await searcher.search(
                    query=search.query,
                    top_k=per_k,
                    rerank=False,
                    node_type_filter=search.node_type_filter,
                    sub_document_id=sd["id"],
                )
                for r in results:
                    r["sub_document_id"] = sd["id"]
                    r["sub_document_key"] = sd["breadcrumb_key"]
                return results
            except Exception as e:
                logger.error(f"Failed to search sub-doc '{sd['breadcrumb_key']}': {e}")
                return []

        all_results = await _gather([_search_one(s) for s in selected])
        logger.info(
            f"Aggregated {len(all_results)} candidates from {len(selected)} sub-docs"
        )
        if not all_results:
            return []

        all_results.sort(key=lambda r: r.get("score", 0), reverse=True)

        if search.rerank:
            all_results = await self._reranker.rerank(
                search.query, all_results, len(all_results)
            )

        top = all_results[: search.top_k]
        if search.context_mode != "none":
            top = expand_context_with_parents(
                top, self._data, search.document_id, search.context_mode
            )
        return top

    async def search_single_index(
        self, search: SingleIndexSearch
    ) -> List[Dict[str, Any]]:
        searcher = self._get_searcher(search.faiss_path, search.bm25_path)
        return await searcher.search(
            query=search.query,
            top_k=search.top_k,
            rerank=search.rerank,
            node_type_filter=search.node_type_filter,
        )

    async def search_collections(
        self, search: CollectionSearch
    ) -> List[Dict[str, Any]]:
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

        metadata = self._build_collection_metadata(collections)
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

        document_concurrency = _document_concurrency()
        document_semaphore = asyncio.Semaphore(document_concurrency)

        async def _search_coll(cd: dict) -> list:
            try:
                docs = self._data.get_completed_documents(cd["id"])
                if not docs:
                    return []

                async def _search_doc(doc: Any) -> list:
                    async with document_semaphore:
                        doc_started = perf_counter()
                        doc_results = await self._search_document(
                            doc,
                            search.query,
                            search.top_k * search.per_document_multiplier,
                            search.hf_api_token,
                            search.node_type_filter,
                        )
                        for r in doc_results:
                            r.update(
                                collection_id=cd["id"],
                                collection_name=cd["name"],
                                document_id=doc.id,
                                document_filename=doc.filename,
                            )
                        logger.info(
                            "Document search completed in %.3fs: collection='%s' document='%s' results=%s",
                            perf_counter() - doc_started,
                            cd["name"],
                            doc.filename,
                            len(doc_results),
                        )
                        return doc_results

                all_doc = await _gather([_search_doc(doc) for doc in docs])
                logger.info(
                    "Collection document searches completed: collection='%s' documents=%s candidates=%s concurrency=%s",
                    cd["name"],
                    len(docs),
                    len(all_doc),
                    document_concurrency,
                )
                return all_doc
            except Exception as e:
                logger.error(f"Failed to search collection '{cd['name']}': {e}")
                return []

        all_results = await _gather([_search_coll(c) for c in selected])
        logger.info(
            "Aggregated %s candidates from %s collections in %.3fs",
            len(all_results),
            len(selected),
            perf_counter() - total_started,
        )
        if not all_results:
            return []

        all_results.sort(key=lambda r: r.get("score", 0), reverse=True)

        if search.rerank:
            all_results = await self._reranker.rerank(
                search.query, all_results, len(all_results)
            )

        top = all_results[: search.top_k]
        if search.context_mode != "none":
            top = self._expand_by_document(top, search.context_mode)
        logger.info(
            "Collection search total time %.3fs: searched_collections=%s returned=%s",
            perf_counter() - total_started,
            len(selected),
            len(top),
        )
        return top

    def _build_subdoc_metadata(self, subdocs: list[Any]) -> list[dict]:
        metadata = []
        for sd in subdocs:
            if not sd.faiss_index_path or not sd.bm25_index_path:
                continue
            card = self._data.get_library_card_for_sub_doc(sd.id)
            page_titles = _parse_page_titles(card)
            metadata.append(
                {
                    "id": sd.id,
                    "breadcrumb_key": sd.breadcrumb_key,
                    "page_titles": page_titles,
                    "page_count": sd.page_count,
                    "faiss_path": sd.faiss_index_path,
                    "bm25_path": sd.bm25_index_path,
                }
            )
        return metadata

    def _build_collection_metadata(self, collections: list[Any]) -> list[dict]:
        metadata = []
        for coll in collections:
            card = self._data.get_collection_library_card(coll.id)
            doc_count, doc_list, summary = _parse_collection_card(card)
            metadata.append(
                {
                    "id": coll.id,
                    "name": coll.name,
                    "library_card_summary": summary,
                    "document_count": doc_count,
                    "document_list": doc_list,
                }
            )
        return metadata

    async def _search_document(
        self,
        doc: Any,
        query: str,
        top_k: int,
        hf_api_token: str | None,
        node_type_filter: list[str] | None = None,
    ) -> list:
        subdoc_count = self._data.count_sub_documents(doc.id)
        if subdoc_count > 0:
            return await self.search_subdocuments(
                SubDocumentSearch(
                    query=query,
                    document_id=doc.id,
                    top_k=top_k,
                    rerank=False,
                    context_mode="none",
                    hf_api_token=hf_api_token,
                    per_subdoc_multiplier=2,
                    node_type_filter=node_type_filter,
                )
            )
        if doc.faiss_index_path and doc.bm25_index_path:
            return await self.search_single_index(
                SingleIndexSearch(
                    query=query,
                    faiss_path=doc.faiss_index_path,
                    bm25_path=doc.bm25_index_path,
                    document_id=doc.id,
                    top_k=top_k,
                    rerank=False,
                    context_mode="none",
                    node_type_filter=node_type_filter,
                )
            )
        return []

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


def _parse_page_titles(card: Any | None) -> list[str]:
    if not (card and card.extra_metadata):
        return []
    try:
        return json.loads(card.extra_metadata).get("page_titles", [])
    except json.JSONDecodeError:
        return []


def _parse_collection_card(card: Any | None) -> tuple[int, list[str], str]:
    if not (card and card.extra_metadata):
        return 0, [], card.content if card else ""
    try:
        meta = json.loads(card.extra_metadata)
        return (
            meta.get("total_documents", 0),
            [d["filename"] for d in meta.get("document_summaries", [])],
            card.content,
        )
    except json.JSONDecodeError:
        return 0, [], card.content


def _select(selector, query: str, metadata: list[dict]) -> list[dict]:
    ids = selector.select(query, metadata)
    return [m for m in metadata if m["id"] in ids]


def _document_concurrency() -> int:
    try:
        return max(1, int(os.getenv("DOCSEARCH_DOCUMENT_CONCURRENCY", "4")))
    except ValueError:
        logger.warning("Invalid DOCSEARCH_DOCUMENT_CONCURRENCY; falling back to 4")
        return 4


async def _gather(tasks: list) -> list:
    nested = await asyncio.gather(*tasks, return_exceptions=True)
    results = []
    for item in nested:
        if isinstance(item, list):
            results.extend(item)
        elif isinstance(item, Exception):
            logger.error(f"Search exception: {item}")
    return results
