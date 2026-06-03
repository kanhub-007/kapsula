"""Structured routing decision for a sub-document candidate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteDecision:
    """Structured routing decision for a sub-document candidate."""

    id: int
    confidence: float = 1.0
    reason: str = ""
