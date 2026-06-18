"""DTO for intelligent-search preparation result.

Closes O1: replaces the heterogeneous 4-tuple returned by the old
``_prepare_intelligent_search`` / ``_db_work`` helpers with a named,
single-source-of-truth structure shared by the API and MCP paths.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchPreparation:
    """Result of preparing an intelligent collection search."""

    plan: dict[str, Any] | None
    collections: list[Any] = field(default_factory=list)
    routed_collection: Any | None = None
    document_structure: list[dict] = field(default_factory=list)
