"""Reciprocal Rank Fusion with quality filtering."""

import logging

from kapsula.core.domain.interfaces.fusion import Fusion
from kapsula.core.domain.quality_filter import (
    apply_fusion_quality_filter,
    normalize_max_sparse,
)

logger = logging.getLogger(__name__)


class RRFFusion(Fusion):
    """Fuses results using Reciprocal Rank Fusion."""

    def __init__(self, k: int = 60):
        self._k = k

    def fuse(
        self,
        dense: list[dict],
        sparse: list[dict],
    ) -> list[dict]:
        result_map: dict[int, dict] = {}
        max_sparse = normalize_max_sparse(sparse)

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
        filtered = apply_fusion_quality_filter(combined, max_sparse)
        logger.debug("Quality filter (RRF): kept %s/%s", len(filtered), len(combined))
        return filtered
