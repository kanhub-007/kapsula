"""Shared helpers for MCP tools — re-export facade.

Groups the DB and infrastructure helpers so tool modules can import
everything from one place (``from ._shared import _get_db, ...``).
Underlying implementations live in :mod:`._db` and :mod:`._infra`.
"""

# ruff: noqa: F401  — this file is a re-export facade; all imports are public API

from kapsula.core.domain.text_processing import (
    parse_node_type_filter as _parse_node_type_filter,  # noqa: F401
)

from ._db import _get_db, _resolve_account, _resolve_collection
from ._infra import (
    _cached,
    _clear_cache,
    _get_chat_client,
    _get_embedder,
    _get_intelligent_searcher,
    _get_maintenance_state_manager,
    _get_multi_index_searcher,
    _get_query_planner,
    _get_reranker,
    _get_search_job_manager,
    _hf_token,
)
