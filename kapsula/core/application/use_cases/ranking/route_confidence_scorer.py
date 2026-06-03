"""Route confidence scoring for search results."""

from __future__ import annotations


class RouteConfidenceScorer:
    """Computes and applies route-confidence weighted scores.

    Route confidence reflects how strongly the routing system believes
    each source (collection and subdocument) is relevant for the query.

    The scorer uses a soft blending formula so that genuinely strong
    results from low-confidence routes are not buried entirely, but
    trusted routes dominate the final ranking.
    """

    def compute_weights(self, results: list[dict]) -> None:
        """Annotate each result with route-weight metadata.

        Stores:
          ``retrieval_score`` — original score before weighting
          ``route_weight``    — combined confidence multiplier
        """
        for result in results:
            retrieval_score = result.get("score", 0.0)
            weight = self._combined_weight(result)
            result["retrieval_score"] = retrieval_score
            result["route_weight"] = weight
            result["score"] = retrieval_score * weight

    def apply_to_scores(self, results: list[dict]) -> None:
        """Re-apply stored route weights to current scores.

        Call this after operations that replace ``score``, such as
        reranking, to preserve route-confidence influence.
        """
        for result in results:
            weight = result.get("route_weight", 1.0)
            current = result.get("score", 0.0)
            result["score"] = current * weight

    def route_weight(self, result: dict) -> float:
        """Return the combined route weight for a result."""
        return self._combined_weight(result)

    @staticmethod
    def _combined_weight(result: dict) -> float:
        collection_confidence = _clamp01(
            float(result.get("collection_route_confidence", 1.0) or 1.0)
        )
        subdocument_confidence = _clamp01(
            float(result.get("subdocument_route_confidence", 1.0) or 1.0)
        )
        return (0.7 + 0.3 * collection_confidence) * (
            0.7 + 0.3 * subdocument_confidence
        )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
