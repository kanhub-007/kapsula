"""Tests for HybridSearcher — Classical school, fakes at boundaries.

Black-box: exercises the documented contract of HybridSearcher — it
gathers dense+sparse retrieval concurrently, fuses them, optionally
filters by node type, optionally reranks, and stamps sub_document_id.
"""

import asyncio

import pytest

from kapsula.core.application.use_cases.hybrid_searcher import HybridSearcher
from kapsula.core.domain.interfaces.fusion import Fusion
from kapsula.core.domain.interfaces.reranker import Reranker
from kapsula.core.domain.interfaces.retriever import Retriever


class FakeRetriever(Retriever):
    """Returns a fixed list of results, recording that retrieve was called."""

    def __init__(self, results: list[dict]):
        self._results = results
        self.calls: list[str] = []

    async def retrieve(self, query: str, k: int) -> list[dict]:
        self.calls.append(query)
        return self._results[:k]


class FakeFusion(Fusion):
    """Concatenates dense + sparse and tags each with a fused score."""

    def fuse(self, dense, sparse):
        merged = []
        for i, r in enumerate(dense):
            merged.append({**r, "score": 0.9 - i * 0.1})
        for i, r in enumerate(sparse):
            merged.append({**r, "score": 0.5 - i * 0.1})
        return merged


class FakeReranker(Reranker):
    """Reverses the order of the first top_k candidates."""

    def __init__(self):
        self.calls: list[tuple[str, list]] = []

    async def rerank(self, query, candidates, top_k):
        self.calls.append((query, list(candidates)))
        reordered = list(reversed(candidates[:top_k]))
        for r in reordered:
            r["rerank_score"] = r.get("score", 0.0) + 0.01
        return reordered


class TestHybridSearcher:
    def test_gathers_dense_and_sparse_and_fuses(self):
        dense = [{"index": 0, "content": "d0"}, {"index": 1, "content": "d1"}]
        sparse = [{"index": 1, "content": "d1"}, {"index": 2, "content": "d2"}]
        dense_r = FakeRetriever(dense)
        sparse_r = FakeRetriever(sparse)
        searcher = HybridSearcher(dense_r, sparse_r, FakeFusion(), reranker=None)

        results = asyncio.run(searcher.search("q", top_k=10, retrieval_k=10))

        assert dense_r.calls == ["q"]
        assert sparse_r.calls == ["q"]
        # Fusion merged both lists (3 unique indices: 0, 1, 2).
        assert {r["index"] for r in results} == {0, 1, 2}
        # Ordering follows the fused score (dense first, higher score).
        assert results[0]["score"] == pytest.approx(0.9)

    def test_strips_query_whitespace(self):
        dense_r = FakeRetriever([])
        sparse_r = FakeRetriever([])
        searcher = HybridSearcher(dense_r, sparse_r, FakeFusion(), None)

        asyncio.run(searcher.search("  q  ", top_k=1))

        assert dense_r.calls == ["q"]
        assert sparse_r.calls == ["q"]

    def test_node_type_filter_drops_non_matching(self):
        dense = [
            {"index": 0, "content": "c0", "metadata": {"node_type": "code"}},
            {"index": 1, "content": "c1", "metadata": {"node_type": "text"}},
            {"index": 2, "content": "c2", "metadata": {"node_type": "table"}},
        ]
        sparse: list[dict] = []
        searcher = HybridSearcher(
            FakeRetriever(dense), FakeRetriever(sparse), FakeFusion(), None
        )

        results = asyncio.run(
            searcher.search("q", top_k=10, node_type_filter=["code", "table"])
        )

        assert {r["index"] for r in results} == {0, 2}

    def test_rerank_path_invokes_reranker_and_returns_its_output(self):
        dense = [{"index": i, "content": f"d{i}"} for i in range(6)]
        sparse: list[dict] = []
        reranker = FakeReranker()
        searcher = HybridSearcher(
            FakeRetriever(dense), FakeRetriever(sparse), FakeFusion(), reranker
        )

        results = asyncio.run(searcher.search("q", top_k=3, rerank=True))

        # Reranker received at most top_k*2 candidates.
        assert reranker.calls
        _q, candidates = reranker.calls[0]
        assert _q == "q"
        assert len(candidates) <= 6
        # FakeReranker reverses; the top result is the one fusion ranked last.
        assert results[0]["index"] == 2
        assert all("rerank_score" in r for r in results)

    def test_rerank_false_does_not_invoke_reranker(self):
        dense = [{"index": 0, "content": "d0"}]
        reranker = FakeReranker()
        searcher = HybridSearcher(
            FakeRetriever(dense), FakeRetriever([]), FakeFusion(), reranker
        )

        asyncio.run(searcher.search("q", top_k=5, rerank=False))

        assert reranker.calls == []

    def test_sub_document_id_is_stamped_on_every_result(self):
        dense = [{"index": 0, "content": "d0"}, {"index": 1, "content": "d1"}]
        sparse: list[dict] = []
        searcher = HybridSearcher(
            FakeRetriever(dense), FakeRetriever(sparse), FakeFusion(), None
        )

        results = asyncio.run(searcher.search("q", top_k=5, sub_document_id=42))

        assert all(r["sub_document_id"] == 42 for r in results)

    def test_sub_document_id_none_leaves_results_untagged(self):
        dense = [{"index": 0, "content": "d0"}]
        searcher = HybridSearcher(
            FakeRetriever(dense), FakeRetriever([]), FakeFusion(), None
        )

        results = asyncio.run(searcher.search("q", top_k=5))

        assert "sub_document_id" not in results[0]
