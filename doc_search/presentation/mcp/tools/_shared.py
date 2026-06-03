"""Shared helpers for MCP tools — re-exports from focused modules.

.. deprecated:: use ``_db`` and ``_infra`` directly in new code.
"""

from ._db import _get_db, _resolve_collection, _resolve_account
from ._infra import (
    _cached,
    _clear_cache,
    _hf_token,
    _get_chat_client,
    _get_query_planner,
    _get_embedder,
    _get_reranker,
    _get_multi_index_searcher,
    _get_intelligent_searcher,
    _get_search_job_manager,
)


def _parse_node_type_filter(node_type_filter: str | None) -> list[str] | None:
    if not node_type_filter:
        return None
    parsed = [item.strip() for item in node_type_filter.split(",") if item.strip()]
    return parsed or None
