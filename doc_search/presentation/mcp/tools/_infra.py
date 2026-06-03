"""Infrastructure singleton cache for MCP tools.

Provides lazy-loaded, cached instances of expensive objects
(embedders, chat clients, rerankers) shared across tool calls.
"""

import os

_cache: dict[str, object] = {}


def _cached(name: str, factory):
    if name not in _cache:
        _cache[name] = factory()
    return _cache[name]


def _clear_cache():
    for obj in _cache.values():
        clear = getattr(obj, "clear_cache", None)
        if callable(clear):
            clear()
    _cache.clear()


def _hf_token():
    return os.getenv("HF_TOKEN") or os.getenv("HF_API_TOKEN")


def _get_chat_client():
    def _create():
        from doc_search.startup import create_chat_client
        return create_chat_client()
    return _cached("chat_client", _create)


def _get_query_planner():
    def _create():
        from doc_search.startup import create_query_planner
        return create_query_planner(_get_chat_client())
    return _cached("query_planner", _create)


def _get_embedder():
    def _create():
        from doc_search.startup import create_embedder
        return create_embedder()
    return _cached("embedder", _create)


def _get_reranker():
    def _create():
        from doc_search.startup import create_reranker
        return create_reranker()
    return _cached("reranker", _create)


def _get_multi_index_searcher(db):
    from doc_search.startup import create_multi_index_searcher
    return create_multi_index_searcher(
        db_session=db,
        embedder=_get_embedder(),
        reranker=_get_reranker(),
        chat_client=_get_chat_client(),
    )


def _get_intelligent_searcher():
    def _create():
        from doc_search.startup import create_intelligent_searcher
        return create_intelligent_searcher(_get_chat_client())
    return _cached("intelligent_searcher", _create)


def _get_search_job_manager():
    def _create():
        from doc_search.presentation.mcp.search_jobs import SearchJobManager
        return SearchJobManager()
    return _cached("search_job_manager", _create)
