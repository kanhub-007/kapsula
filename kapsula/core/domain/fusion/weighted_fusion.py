"""Weighted-score fusion with quality filtering."""

import logging

from kapsula.core.domain.fusion.base_fusion import BaseFusion

logger = logging.getLogger(__name__)


class WeightedFusion(BaseFusion):
    """Fuses results by weighted combination of dense and sparse scores."""

    def __init__(self, dense_weight: float = 0.7, sparse_weight: float = 0.3):
        self._dense_weight = dense_weight
        self._sparse_weight = sparse_weight

    def _dense_score(self, item: dict) -> float:
        return self._dense_weight * item.get("dense_score", 0)

    def _sparse_score(self, item: dict, max_sparse: float) -> float:
        normalized = item.get("sparse_score", 0) / max_sparse if max_sparse else 0.0
        return self._sparse_weight * normalized
