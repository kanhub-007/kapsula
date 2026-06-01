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
    return any(cond(dense, sparse_normalized, max_sparse) for cond in _QUALITY_CONDITIONS)
