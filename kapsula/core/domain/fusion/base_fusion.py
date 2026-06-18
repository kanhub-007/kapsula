"""Base fusion skeleton — Template Method for combining dense + sparse results.

Closes P4: ``RRFFusion`` and ``WeightedFusion`` previously duplicated the
map-build → sort → quality-filter skeleton. This base holds the skeleton;
subclasses override only the per-branch score computation.
"""

import logging
from typing import Any

from kapsula.core.domain.interfaces.fusion import Fusion
from kapsula.core.domain.quality_filter import (
    apply_fusion_quality_filter,
    normalize_max_sparse,
)

logger = logging.getLogger(__name__)


class BaseFusion(Fusion):
    """Template Method base for fusion strategies.

    Subclasses implement :meth:`_dense_score` and :meth:`_sparse_score`;
    everything else (dedup map construction, sorting, quality filtering)
    is shared.
    """

    def fuse(
        self, dense: list[dict[str, Any]], sparse: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        max_sparse = normalize_max_sparse(sparse)
        result_map: dict[int, dict] = {}

        for item in dense:
            idx = item["index"]
            if idx not in result_map:
                result_map[idx] = self._new_entry(item)
            result_map[idx]["score"] += self._dense_score(item)
            result_map[idx]["dense_score"] = item.get("dense_score", 0)

        for item in sparse:
            idx = item["index"]
            if idx not in result_map:
                result_map[idx] = self._new_entry(item)
            result_map[idx]["score"] += self._sparse_score(item, max_sparse)
            result_map[idx]["sparse_score"] = item.get("sparse_score", 0)

        combined = sorted(result_map.values(), key=lambda x: x["score"], reverse=True)
        filtered = apply_fusion_quality_filter(combined, max_sparse)
        logger.debug(
            "Quality filter (%s): kept %s/%s",
            type(self).__name__,
            len(filtered),
            len(combined),
        )
        return filtered

    # ── hooks ────────────────────────────────────────────────

    def _new_entry(self, item: dict[str, Any]) -> dict[str, Any]:
        """Build the initial result-map entry for a new index."""
        return {
            "index": item["index"],
            "content": item["content"],
            "score": 0.0,
            "dense_score": 0.0,
            "sparse_score": 0.0,
        }

    def _dense_score(self, item: dict[str, Any]) -> float:
        raise NotImplementedError

    def _sparse_score(self, item: dict[str, Any], max_sparse: float) -> float:
        raise NotImplementedError
