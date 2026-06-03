"""Structured routing decision for a collection candidate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectionRouteDecision:
    """Structured routing decision for a collection candidate."""

    id: int
    confidence: float = 1.0
    reason: str = ""
