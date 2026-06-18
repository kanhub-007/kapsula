"""Domain-level quality filter for search results."""

_QUALITY_CONDITIONS = [
    lambda d, sn, cs: d > 0.15 and sn > 0.1,
    lambda d, sn, cs: d >= 0.55 and sn > 0.02,
    lambda d, sn, cs: d >= 0.4 and sn > 0.05,
    lambda d, sn, cs: sn >= 0.3 and d >= 0.25,
]


def passes_quality_filter(
    dense: float, sparse_normalized: float, max_sparse: float
) -> bool:
    """Check whether a fused search result meets minimum quality thresholds.

    Uses a disjunction of heuristic conditions that balance dense (semantic)
    and sparse (lexical) scores. If any condition passes, the result
    is considered high-quality.

    Args:
        dense: Dense (FAISS) similarity score, typically 0.0–1.0.
        sparse_normalized: Normalized BM25 score.
        max_sparse: Maximum BM25 score in the result set (unused directly).

    Returns:
        True if the (dense, sparse) pair passes at least one condition.
    """
    return any(
        cond(dense, sparse_normalized, max_sparse) for cond in _QUALITY_CONDITIONS
    )
