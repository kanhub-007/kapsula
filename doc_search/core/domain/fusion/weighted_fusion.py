"""Weighted-score fusion with quality filtering."""

from typing import List, Dict, Any

import logging

from doc_search.core.domain.quality_filter import passes_quality_filter

logger = logging.getLogger(__name__)


class WeightedFusion:
    """Fuses results by weighted combination of dense and sparse scores."""

    def __init__(self, dense_weight: float = 0.7, sparse_weight: float = 0.3):
        self._dense_weight = dense_weight
        self._sparse_weight = sparse_weight

    def fuse(
        self, dense: List[Dict[str, Any]], sparse: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        sparse_scores = [
            r["sparse_score"] for r in sparse if r.get("sparse_score", 0) > 0
        ]
        max_sparse = max(sparse_scores) if sparse_scores else 1.0

        result_map: dict[int, dict] = {}

        for item in dense:
            idx = item["index"]
            result_map[idx] = {
                "index": idx,
                "content": item["content"],
                "dense_score": item.get("dense_score", 0),
                "sparse_score": 0.0,
                "score": self._dense_weight * item.get("dense_score", 0),
            }

        for item in sparse:
            idx = item["index"]
            ns = item.get("sparse_score", 0) / max_sparse
            if idx in result_map:
                result_map[idx]["sparse_score"] = item.get("sparse_score", 0)
                result_map[idx]["score"] += self._sparse_weight * ns
            else:
                result_map[idx] = {
                    "index": idx,
                    "content": item["content"],
                    "dense_score": 0.0,
                    "sparse_score": item.get("sparse_score", 0),
                    "score": self._sparse_weight * ns,
                }

        combined = sorted(result_map.values(), key=lambda x: x["score"], reverse=True)
        return _apply_quality_filter(combined, max_sparse)


def _apply_quality_filter(
    combined: List[Dict[str, Any]], max_sparse: float
) -> List[Dict[str, Any]]:
    filtered = []
    for result in combined:
        dense = result.get("dense_score", 0)
        sn = (
            result.get("sparse_score", 0) / max_sparse if max_sparse > 0 else 0
        )
        if passes_quality_filter(dense, sn, max_sparse):
            filtered.append(result)
    logger.debug(f"Quality filter: kept {len(filtered)}/{len(combined)}")
    return filtered
