"""Tests for MultiIndexSearcher — Classical school, fakes at boundaries.

Black-box: exercises sub-document search and collection search with fakes
for the data-access layer, routing strategies, and the per-index searcher
factory. Asserts on returned results, never on call interactions.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from kapsula.core.application.dto.collection_search import CollectionSearch
from kapsula.core.application.dto.single_document_search import (
    SingleDocumentSearch,
)
from kapsula.core.application.dto.sub_document_search import SubDocumentSearch
from kapsula.core.application.use_cases.multi_index_searcher import (
    MultiIndexSearcher,
)
from kapsula.core.application.use_cases.ranking.source_quota_policy import (
    SourceQuotaPolicy,
)
from kapsula.core.domain.interfaces.chat_client import ChatClient


class FakeChatClient(ChatClient):
    """Returns a canned response (used by routing selectors)."""

    def send(self, messages, max_tokens=500, temperature=0.3) -> str:
        return "1,2,3"


@dataclass
class _FakeSubDoc:
    """Mimics the attributes MultiIndexSearcher reads from a sub-document."""

    id: int
    breadcrumb_key: str
    faiss_index_path: str | None
    bm25_index_path: str | None
    page_count: int = 1


@dataclass
class _FakeCard:
    content: str = "summary"
    page_titles: list[str] | None = None
    extra_metadata: str | None = None


@dataclass
class _FakeCollection:
    """Attribute-accessible collection stand-in (matches SearchMetadataBuilder reads)."""

    id: int
    name: str
    collection_id: str
    account: Any = None


class FakeSearchDataAccess:
    """In-memory SearchDataAccess stand-in (dict-backed)."""

    def __init__(
        self,
        subdocs: list[_FakeSubDoc] | None = None,
        cards: dict[int, _FakeCard] | None = None,
        collections: list[_FakeCollection] | None = None,
        completed_docs: dict[int, list] | None = None,
    ):
        self._subdocs = subdocs or []
        self._cards = cards or {}
        self._collections = collections or []
        self._completed = completed_docs or {}

    def get_sub_documents(self, document_id):
        return self._subdocs

    def get_library_card_for_sub_doc(self, sub_doc_id):
        return self._cards.get(sub_doc_id, _FakeCard())

    def get_completed_documents(self, collection_id):
        return self._completed.get(collection_id, [])

    def get_collections_by_account(self, account_id):
        return self._collections

    def get_all_collections(self):
        return self._collections

    def get_collection_by_collection_id(self, collection_id):
        return next(
            (c for c in self._collections if c.collection_id == collection_id),
            None,
        )

    def get_collection_library_card(self, collection_id):
        return _FakeCard(content=f"collection {collection_id}")

    # Methods below are unused by the paths under test but required by the
    # Protocol shape; return harmless defaults.
    def get_library_card_by_doc_id(self, doc_id, sub_doc_id=None):
        return None

    def get_chunk(self, document_id, chunk_index, sub_doc_id=None):
        return None

    def get_chunks_batch(self, document_id, chunk_specs):
        return {}

    def get_library_cards_by_doc_ids(self, doc_ids):
        return {}

    def count_sub_documents(self, document_id):
        return len(self._subdocs)


def _make_searcher(make_searcher_fn, data, strategies=None):
    return MultiIndexSearcher(
        data=data,
        embedder=object(),  # unused — make_searcher is faked
        reranker=None,
        chat_client=FakeChatClient(),
        make_searcher=make_searcher_fn,
        strategies=strategies or [],
    )


class _FakeIndexSearcher:
    """Returns a fixed list of results per search call."""

    def __init__(self, results: list[dict]):
        self._results = results

    async def search(self, **kwargs):
        return [dict(r) for r in self._results]


class TestSearchSubdocuments:
    def test_no_subdocuments_returns_empty(self):
        data = FakeSearchDataAccess(subdocs=[])
        searcher = _make_searcher(lambda faiss, bm25: None, data)

        results = asyncio.run(
            searcher.search_subdocuments(
                SubDocumentSearch(query="q", document_id=1, context_mode="none")
            )
        )

        assert results == []

    def test_returns_results_tagged_with_sub_document_id(self):
        subdocs = [
            _FakeSubDoc(
                id=10, breadcrumb_key="ch1", faiss_index_path="a", bm25_index_path="b"
            ),
        ]
        data = FakeSearchDataAccess(subdocs=subdocs)
        fake_index = _FakeIndexSearcher([{"index": 0, "content": "hit", "score": 0.9}])
        searcher = _make_searcher(lambda faiss, bm25: fake_index, data)

        results = asyncio.run(
            searcher.search_subdocuments(
                SubDocumentSearch(query="q", document_id=1, context_mode="none")
            )
        )

        assert len(results) == 1
        assert results[0].sub_document_id == 10
        assert results[0].sub_document_key == "ch1"


class TestSourceQuotaPolicy:
    """Direct unit tests for the quota policy (used by the non-fast path)."""

    def test_select_truncates_to_top_k(self):
        policy = SourceQuotaPolicy()
        results = [{"index": i, "score": 1.0 - i * 0.1} for i in range(10)]

        selected = policy.select(results, top_k=3)

        assert len(selected) == 3

    def test_apply_preserves_overflow_for_backup(self):
        """apply keeps overflow (by design) so the caller can fall back."""
        policy = SourceQuotaPolicy()
        results = [{"index": i, "score": 0.5} for i in range(10)]

        applied = policy.apply(results, top_k=3)

        # All results retained (preferred first, overflow after).
        assert len(applied) == 10


class TestSearchCollections:
    def test_no_collections_returns_empty(self):
        data = FakeSearchDataAccess(collections=[])
        searcher = _make_searcher(lambda faiss, bm25: None, data)

        search = CollectionSearch(query="q")
        search.account_id = "acc-1"  # forces ACCOUNT scope with empty result

        results = asyncio.run(searcher.search_collections(search))

        assert results == []

    def test_aggregate_fast_path_returns_strategy_results(self):
        """When an injected strategy yields non-None, the caller uses it directly."""

        class _HitStrategy:
            async def search(
                self,
                collection,
                query,
                top_k,
                per_document_multiplier,
                context_mode,
                node_type_filter,
            ):
                return [{"index": 0, "content": "agg", "score": 0.99}]

        data = FakeSearchDataAccess(
            collections=[_FakeCollection(id=1, name="c1", collection_id="c-1")]
        )
        searcher = _make_searcher(
            lambda faiss, bm25: None, data, strategies=[_HitStrategy()]
        )
        search = CollectionSearch(query="q", collection_id="c-1")

        results = asyncio.run(searcher.search_collections(search))

        assert len(results) == 1
        assert results[0].content == "agg"

    def test_aggregate_fast_path_sorts_by_score(self):
        """The fast path sorts strategy results by score descending."""

        class _UnsortedStrategy:
            async def search(
                self,
                collection,
                query,
                top_k,
                per_document_multiplier,
                context_mode,
                node_type_filter,
            ):
                return [
                    {"index": 0, "content": "low", "score": 0.1},
                    {"index": 1, "content": "high", "score": 0.9},
                    {"index": 2, "content": "mid", "score": 0.5},
                ]

        data = FakeSearchDataAccess(
            collections=[_FakeCollection(id=1, name="c1", collection_id="c-1")]
        )
        searcher = _make_searcher(
            lambda faiss, bm25: None, data, strategies=[_UnsortedStrategy()]
        )
        search = CollectionSearch(query="q", collection_id="c-1")

        results = asyncio.run(searcher.search_collections(search))

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
        assert results[0].content == "high"


class TestSearchDocumentDispatch:
    """H5: search_document picks subdoc vs flat based on architecture."""

    def test_dispatches_to_subdocuments_when_present(self):
        subdocs = [
            _FakeSubDoc(
                id=10, breadcrumb_key="ch", faiss_index_path="a", bm25_index_path="b"
            )
        ]
        data = FakeSearchDataAccess(subdocs=subdocs)
        fake = _FakeIndexSearcher([{"index": 0, "content": "hit", "score": 0.9}])
        searcher = _make_searcher(lambda faiss, bm25: fake, data)

        results = asyncio.run(
            searcher.search_document(
                SingleDocumentSearch(
                    query="q",
                    document_id=1,
                    faiss_path="ignored",
                    bm25_path="ignored",
                    context_mode="none",
                )
            )
        )

        assert len(results) == 1
        assert results[0].sub_document_id == 10
        assert results[0].document_id == 1

    def test_dispatches_to_single_index_when_no_subdocuments(self):
        data = FakeSearchDataAccess(subdocs=[])
        fake = _FakeIndexSearcher([{"index": 4, "content": "flat", "score": 0.5}])
        searcher = _make_searcher(lambda faiss, bm25: fake, data)

        results = asyncio.run(
            searcher.search_document(
                SingleDocumentSearch(
                    query="q",
                    document_id=7,
                    faiss_path="f.faiss",
                    bm25_path="b.pkl",
                    context_mode="none",
                )
            )
        )

        assert len(results) == 1
        assert results[0].content == "flat"
        assert results[0].document_id == 7

    def test_flat_without_indexes_raises(self):
        data = FakeSearchDataAccess(subdocs=[])
        searcher = _make_searcher(lambda faiss, bm25: None, data)

        with pytest.raises(ValueError, match="No search indexes"):
            asyncio.run(
                searcher.search_document(
                    SingleDocumentSearch(
                        query="q",
                        document_id=7,
                        faiss_path=None,
                        bm25_path=None,
                    )
                )
            )
