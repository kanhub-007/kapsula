"""Domain-level quality filter for search results.

Quality thresholds and the shared fusion post-filter live here so both fusion
strategies (RRF, Weighted) apply identical filtering logic without duplicating
it. See :mod:`kapsula.core.domain.fusion.rrf_fusion` and
:mod:`weighted_fusion`.
"""

from collections.abc import Callable
from typing import Any

_QUALITY_CONDITIONS: list[Callable[[float, float, float], bool]] = [
    lambda d, sn, cs: d > 0.15 and sn > 0.1,
    lambda d, sn, cs: d >= 0.55 and sn > 0.02,
    lambda d, sn, cs: d >= 0.4 and sn > 0.05,
    lambda d, sn, cs: sn >= 0.3 and d >= 0.25,
]


def normalize_max_sparse(sparse: list[dict]) -> float:
    """Return the max sparse score in the set, or 1.0 if none are positive."""
    scores = [r["sparse_score"] for r in sparse if r.get("sparse_score", 0) > 0]
    return max(scores) if scores else 1.0


def passes_quality_filter(dense: float, sparse_normalized: float) -> bool:
    """Check whether a fused search result meets minimum quality thresholds.

    Uses a disjunction of heuristic conditions that balance dense (semantic)
    and sparse (lexical) scores. If any condition passes, the result is
    considered high-quality.

    Args:
        dense: Dense (FAISS) similarity score, typically 0.0–1.0.
        sparse_normalized: Normalized BM25 score (max-scaled to ~0.0–1.0).

    Returns:
        True if the (dense, sparse) pair passes at least one condition.
    """
    return any(cond(dense, sparse_normalized, 0.0) for cond in _QUALITY_CONDITIONS)


def apply_fusion_quality_filter(
    combined: list[dict[str, Any]], max_sparse: float
) -> list[dict[str, Any]]:
    """Filter fused results by quality, normalising each sparse score.

    Shared by RRF and Weighted fusion so the post-filter cannot drift between
    strategies. ``max_sparse`` is the largest raw sparse score in the set;
    each result's ``sparse_score`` is divided by it (guarded against zero).
    """
    filtered: list[dict[str, Any]] = []
    for result in combined:
        dense = result.get("dense_score", 0.0)
        sn = result.get("sparse_score", 0.0) / max_sparse if max_sparse > 0 else 0.0
        if passes_quality_filter(dense, sn):
            filtered.append(result)
    return filtered
