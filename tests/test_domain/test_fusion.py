"""Tests for fusion strategies and the quality filter (Classical school).

Black-box: exercises the documented contract of RRFFusion and WeightedFusion —
fusing dense+sparse ranked lists into a deduplicated, quality-filtered, sorted
list. Also tests the shared quality-filter thresholds directly.
"""

import pytest

from kapsula.core.domain.fusion.rrf_fusion import RRFFusion
from kapsula.core.domain.fusion.weighted_fusion import WeightedFusion
from kapsula.core.domain.interfaces.fusion import Fusion
from kapsula.core.domain.quality_filter import (
    apply_fusion_quality_filter,
    normalize_max_sparse,
    passes_quality_filter,
)


def _dense(idx: int, score: float, rank: int) -> dict:
    return {
        "index": idx,
        "content": f"d{idx}",
        "dense_score": score,
        "original_rank": rank,
    }


def _sparse(idx: int, score: float, rank: int) -> dict:
    return {
        "index": idx,
        "content": f"s{idx}",
        "sparse_score": score,
        "original_rank": rank,
    }


def _pair(idx: int, dense_score: float, sparse_score: float, rank: int = 0) -> tuple:
    """Build a (dense, sparse) entry that survives the quality filter."""
    return _dense(idx, dense_score, rank), _sparse(idx, sparse_score, rank)


@pytest.fixture(params=[RRFFusion(), WeightedFusion()])
def fusion(request) -> Fusion:
    """Both strategies must satisfy the same contract."""
    return request.param


class TestFusionContract:
    """Shared contract for both fusion strategies."""

    def test_both_strategies_implement_fusion_protocol(self):
        assert isinstance(RRFFusion(), Fusion)
        assert isinstance(WeightedFusion(), Fusion)

    def test_empty_inputs_return_empty(self, fusion):
        assert fusion.fuse([], []) == []

    def test_union_of_indices(self, fusion):
        # Every index carries both dense and sparse signal (realistic for
        # overlapping retriever output) so the quality filter keeps all.
        d1, s1 = _pair(1, 0.9, 5.0)
        d2, s2 = _pair(2, 0.8, 4.0)
        d3, s3 = _pair(3, 0.7, 4.0)
        out = fusion.fuse([d1, d2, d3], [s1, s2, s3])
        indices = {r["index"] for r in out}
        assert indices == {1, 2, 3}

    def test_results_sorted_descending_by_score(self, fusion):
        pairs = [_pair(i, 0.9 - i * 0.1, 5.0 - i * 0.5, rank=i) for i in range(5)]
        dense = [p[0] for p in pairs]
        sparse = [p[1] for p in pairs]
        out = fusion.fuse(dense, sparse)
        scores = [r["score"] for r in out]
        assert scores == sorted(scores, reverse=True)

    def test_result_keeps_content_and_index(self, fusion):
        d7, s7 = _pair(7, 0.9, 5.0)
        out = fusion.fuse([d7], [s7])
        assert out[0]["index"] == 7

    def test_quality_filter_drops_low_score_noise(self, fusion):
        # Index 99 has trivial scores in both — should be filtered out.
        d1, s1 = _pair(1, 0.9, 5.0)
        dense = [d1, _dense(99, 0.01, 1)]
        sparse = [s1]
        out = fusion.fuse(dense, sparse)
        indices = {r["index"] for r in out}
        assert 99 not in indices


class TestRRFFusion:
    def test_higher_rank_contributes_more(self):
        rrf = RRFFusion(k=60)
        d1, s1 = _pair(1, 0.9, 5.0, rank=0)
        d2, s2 = _pair(2, 0.9, 5.0, rank=10)
        out = rrf.fuse([d1, d2], [s1, s2])
        by_idx = {r["index"]: r["score"] for r in out}
        assert by_idx[1] > by_idx[2]

    def test_index_in_both_lists_populates_both_scores(self):
        rrf = RRFFusion(k=60)
        d1, s1 = _pair(1, 0.9, 5.0, rank=0)
        out = rrf.fuse([d1], [s1])
        by_idx = {r["index"]: r for r in out}
        # Present in both -> both sub-scores populated (not the default 0)
        assert by_idx[1]["dense_score"] == 0.9
        assert by_idx[1]["sparse_score"] == 5.0


class TestWeightedFusion:
    def test_dense_weight_applied(self):
        wf = WeightedFusion(dense_weight=0.7, sparse_weight=0.3)
        d1, s1 = _pair(1, 1.0, 5.0)
        out = wf.fuse([d1], [s1])
        # score = 0.7*1.0 + 0.3*(5.0/5.0) = 1.0
        assert out[0]["score"] == pytest.approx(1.0)

    def test_sparse_weight_uses_normalized_score(self):
        wf = WeightedFusion(dense_weight=0.5, sparse_weight=0.5)
        # dense chosen so the quality filter passes (d>0.15 and sn>0.1).
        d1, s1 = _pair(1, 0.2, 5.0)
        d2, s2 = _pair(2, 0.2, 2.5)
        out = wf.fuse([d1, d2], [s1, s2])
        by_idx = {r["index"]: r["score"] for r in out}
        # score = 0.5*0.2 + 0.5*(sparse/max=5.0)
        # index1: 0.1 + 0.5*1.0 = 0.6 ; index2: 0.1 + 0.5*0.5 = 0.35
        assert by_idx[1] == pytest.approx(0.6)
        assert by_idx[2] == pytest.approx(0.35)


class TestQualityFilter:
    @pytest.mark.parametrize(
        "dense,sparse,expected",
        [
            (0.2, 0.2, True),  # d>0.15 and sn>0.1
            (0.6, 0.03, True),  # d>=0.55 and sn>0.02
            (0.45, 0.06, True),  # d>=0.4 and sn>0.05
            (0.3, 0.35, True),  # sn>=0.3 and d>=0.25
            (0.05, 0.05, False),  # nothing passes
            (
                0.9,
                0.0,
                False,
            ),  # dense high but sparse 0; none of the AND conditions hold
        ],
    )
    def test_thresholds(self, dense, sparse, expected):
        assert passes_quality_filter(dense, sparse) is expected

    def test_apply_filter_normalises_sparse(self):
        combined = [
            {"index": 1, "dense_score": 0.6, "sparse_score": 10.0},  # sn=1.0 -> pass
            {"index": 2, "dense_score": 0.01, "sparse_score": 0.1},  # -> fail
        ]
        out = apply_fusion_quality_filter(combined, max_sparse=10.0)
        assert [r["index"] for r in out] == [1]

    def test_normalize_max_sparse_empty(self):
        assert normalize_max_sparse([]) == 1.0

    def test_normalize_max_sparse_all_zero(self):
        assert normalize_max_sparse([_sparse(1, 0.0, 0)]) == 1.0
