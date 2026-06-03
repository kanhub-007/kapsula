"""Reciprocal Rank Fusion with quality filtering."""

from typing import List, Dict, Any

import logging

from kapsula.core.domain.quality_filter import passes_quality_filter

logger = logging.getLogger(__name__)


class RRFFusion:
    """Fuses results using Reciprocal Rank Fusion."""

    def __init__(self, k: int = 60):
        self._k = k

    def fuse(
        self, dense: List[Dict[str, Any]], sparse: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        result_map: dict[int, dict] = {}
        sparse_scores = [
            r["sparse_score"] for r in sparse if r.get("sparse_score", 0) > 0
        ]
        max_sparse = max(sparse_scores) if sparse_scores else 1.0

        for item in dense:
            idx = item["index"]
            rrf = 1 / (self._k + item["original_rank"] + 1)
            if idx not in result_map:
                result_map[idx] = {
                    "index": idx,
                    "content": item["content"],
                    "score": 0.0,
                    "dense_score": item.get("dense_score", 0),
                    "sparse_score": 0.0,
                }
            result_map[idx]["score"] += rrf

        for item in sparse:
            idx = item["index"]
            rrf = 1 / (self._k + item["original_rank"] + 1)
            if idx not in result_map:
                result_map[idx] = {
                    "index": idx,
                    "content": item["content"],
                    "score": 0.0,
                    "dense_score": 0.0,
                    "sparse_score": item.get("sparse_score", 0),
                }
            result_map[idx]["score"] += rrf
            result_map[idx]["sparse_score"] = item.get("sparse_score", 0)

        combined = sorted(result_map.values(), key=lambda x: x["score"], reverse=True)
        return _apply_quality_filter(combined, max_sparse)


def _apply_quality_filter(
    combined: List[Dict[str, Any]], max_sparse: float
) -> List[Dict[str, Any]]:
    filtered = []
    for result in combined:
        dense = result.get("dense_score", 0)
        sn = result.get("sparse_score", 0) / max_sparse if max_sparse > 0 else 0
        if passes_quality_filter(dense, sn, max_sparse):
            filtered.append(result)
    logger.debug(f"Quality filter: kept {len(filtered)}/{len(combined)}")
    return filtered
