"""Reciprocal Rank Fusion with quality filtering."""

import logging

from kapsula.core.domain.fusion.base_fusion import BaseFusion

logger = logging.getLogger(__name__)


class RRFFusion(BaseFusion):
    """Fuses results using Reciprocal Rank Fusion."""

    def __init__(self, k: int = 60):
        self._k = k

    def _dense_score(self, item: dict) -> float:
        return 1 / (self._k + item["original_rank"] + 1)

    def _sparse_score(self, item: dict, max_sparse: float) -> float:
        return 1 / (self._k + item["original_rank"] + 1)
