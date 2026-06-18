"""Weighted-score fusion with quality filtering."""

import logging

from kapsula.core.domain.interfaces.fusion import Fusion
from kapsula.core.domain.quality_filter import (
    apply_fusion_quality_filter,
    normalize_max_sparse,
)

logger = logging.getLogger(__name__)


class WeightedFusion(Fusion):
    """Fuses results by weighted combination of dense and sparse scores."""

    def __init__(self, dense_weight: float = 0.7, sparse_weight: float = 0.3):
        self._dense_weight = dense_weight
        self._sparse_weight = sparse_weight

    def fuse(
        self,
        dense: list[dict],
        sparse: list[dict],
    ) -> list[dict]:
        max_sparse = normalize_max_sparse(sparse)
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
        filtered = apply_fusion_quality_filter(combined, max_sparse)
        logger.debug(
            "Quality filter (Weighted): kept %s/%s", len(filtered), len(combined)
        )
        return filtered
