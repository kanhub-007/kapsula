"""Multi-index search aggregator for Russian Doll retrieval."""

import asyncio
import json
import logging
from typing import Callable
from typing import List, Dict, Any

from doc_search.core.application.dto.collection_search import CollectionSearch
from doc_search.core.application.dto.single_index_search import SingleIndexSearch
from doc_search.core.application.dto.sub_document_search import SubDocumentSearch
from doc_search.core.application.use_cases.context_expansion import expand_context_with_parents
from doc_search.core.application.use_cases.selectors.collection_selector import CollectionSelector
from doc_search.core.application.use_cases.selectors.sub_document_selector import SubDocumentSelector
from doc_search.core.domain.interfaces.chat_client import ChatClient
from doc_search.core.domain.interfaces.embedder import Embedder
from doc_search.core.domain.interfaces.reranker import Reranker
from doc_search.core.domain.interfaces.search_data_access import SearchDataAccess
from doc_search.infrastructure.data.tables.collection import Collection
from doc_search.infrastructure.data.tables.document import Document
from doc_search.infrastructure.data.tables.library_card import LibraryCard
from doc_search.infrastructure.data.tables.sub_document import SubDocument

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
        selected = _select(selector, search.query, metadata)
        if not selected:
            return []

        logger.info(f"Multi-index search: {len(selected)}/{len(subdocs)} sub-docs")
        per_k = search.top_k * search.per_subdoc_multiplier

        async def _search_one(sd: dict) -> list:
            try:
                searcher = self._get_searcher(sd["faiss_path"], sd["bm25_path"])
                results = await searcher.search(
                    query=search.query, top_k=per_k, rerank=False,
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
        logger.info(f"Aggregated {len(all_results)} candidates from {len(selected)} sub-docs")
        if not all_results:
            return []

        all_results.sort(key=lambda r: r.get("score", 0), reverse=True)

        if search.rerank:
            all_results = await self._reranker.rerank(search.query, all_results, len(all_results))

        top = all_results[:search.top_k]
        if search.context_mode != "none":
            top = expand_context_with_parents(top, self._data, search.document_id, search.context_mode)
        return top

    async def search_single_index(
        self, search: SingleIndexSearch
    ) -> List[Dict[str, Any]]:
        searcher = self._get_searcher(search.faiss_path, search.bm25_path)
        return await searcher.search(
            query=search.query, top_k=search.top_k, rerank=search.rerank,
        )

    async def search_collections(
        self, search: CollectionSearch
    ) -> List[Dict[str, Any]]:
        if search.account_id:
            collections = self._data.get_collections_by_account(search.account_id)
        else:
            collections = self._data.get_all_collections()
        if not collections:
            return []

        metadata = self._build_collection_metadata(collections)
        selector = CollectionSelector(self._chat_client)
        selected = _select(selector, search.query, metadata)
        if not selected:
            return []

        logger.info(f"Collection search: {len(selected)}/{len(collections)} collections")

        async def _search_coll(cd: dict) -> list:
            try:
                docs = self._data.get_completed_documents(cd["id"])
                if not docs:
                    return []
                all_doc = []
                for doc in docs:
                    doc_results = await self._search_document(
                        doc, search.query, search.top_k * search.per_document_multiplier, search.hf_api_token
                    )
                    for r in doc_results:
                        r.update(
                            collection_id=cd["id"], collection_name=cd["name"],
                            document_id=doc.id, document_filename=doc.filename,
                        )
                    all_doc.extend(doc_results)
                return all_doc
            except Exception as e:
                logger.error(f"Failed to search collection '{cd['name']}': {e}")
                return []

        all_results = await _gather([_search_coll(c) for c in selected])
        logger.info(f"Aggregated {len(all_results)} candidates from {len(selected)} collections")
        if not all_results:
            return []

        all_results.sort(key=lambda r: r.get("score", 0), reverse=True)

        if search.rerank:
            all_results = await self._reranker.rerank(search.query, all_results, len(all_results))

        top = all_results[:search.top_k]
        if search.context_mode != "none":
            top = self._expand_by_document(top, search.context_mode)
        return top

    def _build_subdoc_metadata(self, subdocs: list[SubDocument]) -> list[dict]:
        metadata = []
        for sd in subdocs:
            if not sd.faiss_index_path or not sd.bm25_index_path:
                continue
            card = self._data.get_library_card_for_sub_doc(sd.id)
            page_titles = _parse_page_titles(card)
            metadata.append({
                "id": sd.id,
                "breadcrumb_key": sd.breadcrumb_key,
                "page_titles": page_titles,
                "page_count": sd.page_count,
                "faiss_path": sd.faiss_index_path,
                "bm25_path": sd.bm25_index_path,
            })
        return metadata

    def _build_collection_metadata(self, collections: list[Collection]) -> list[dict]:
        metadata = []
        for coll in collections:
            card = self._data.get_collection_library_card(coll.id)
            doc_count, doc_list, summary = _parse_collection_card(card)
            metadata.append({
                "id": coll.id, "name": coll.name,
                "library_card_summary": summary,
                "document_count": doc_count, "document_list": doc_list,
            })
        return metadata

    async def _search_document(
        self, doc: Document, query: str, top_k: int, hf_api_token: str | None
    ) -> list:
        subdoc_count = self._data.count_sub_documents(doc.id)
        if subdoc_count > 0:
            return await self.search_subdocuments(
                SubDocumentSearch(
                    query=query, document_id=doc.id, top_k=top_k,
                    rerank=False, context_mode="none",
                    hf_api_token=hf_api_token, per_subdoc_multiplier=2,
                )
            )
        if doc.faiss_index_path and doc.bm25_index_path:
            return await self.search_single_index(
                SingleIndexSearch(
                    query=query, faiss_path=doc.faiss_index_path,
                    bm25_path=doc.bm25_index_path, document_id=doc.id,
                    top_k=top_k, rerank=False, context_mode="none",
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
                expand_context_with_parents(doc_results, self._data, doc_id, context_mode)
            )
        return expanded


def _parse_page_titles(card: LibraryCard | None) -> list[str]:
    if not (card and card.extra_metadata):
        return []
    try:
        return json.loads(card.extra_metadata).get("page_titles", [])
    except json.JSONDecodeError:
        return []


def _parse_collection_card(card: LibraryCard | None) -> tuple[int, list[str], str]:
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


async def _gather(tasks: list) -> list:
    nested = await asyncio.gather(*tasks, return_exceptions=True)
    results = []
    for item in nested:
        if isinstance(item, list):
            results.extend(item)
        elif isinstance(item, Exception):
            logger.error(f"Search exception: {item}")
    return results
