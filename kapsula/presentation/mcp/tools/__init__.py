"""MCP tools — kapsula operations exposed to MCP clients.

Each tool group lives in its own module and is registered via
a ``register_*_tools(mcp)`` function called by :func:`register_tools`.
"""

from fastmcp import FastMCP

from ._shared import (
    _clear_cache,
    _get_chat_client,
    _get_embedder,
    _get_intelligent_searcher,
    _get_multi_index_searcher,
    _get_query_planner,
    _get_reranker,
)
from .accounts import register_account_tools
from .collections import register_collection_tools
from .documents import register_document_tools
from .export import register_export_tools
from .search import register_search_tools

# Re-exported so tests and other presentation modules can import shared
# infrastructure helpers from the tools package root.
__all__ = [
    "_clear_cache",
    "_get_chat_client",
    "_get_embedder",
    "_get_intelligent_searcher",
    "_get_multi_index_searcher",
    "_get_query_planner",
    "_get_reranker",
    "register_tools",
]


def _memory_guide_text() -> str:
    """Return the full usage guide for AI assistants.

    Loaded from ``memory_guide.md`` packaged alongside this module (closes L7:
    was a ~70-line string literal that was painful to edit and review).
    """
    from importlib.resources import files

    return (
        files("kapsula.presentation.mcp.tools")
        .joinpath("memory_guide.md")
        .read_text(encoding="utf-8")
    )


def register_tools(mcp: FastMCP):
    """Register all kapsula tools on the given MCP server instance."""
    register_account_tools(mcp)
    register_collection_tools(mcp)
    register_document_tools(mcp)
    register_search_tools(mcp)
    register_export_tools(mcp)

    @mcp.tool(
        name="get_memory_guide",
        description=(
            "Return a usage guide explaining how kapsula works as a memory system — "
            "the hierarchy, writing knowledge, searching, updating, and best practices. "
            "Call this FIRST if you're new to kapsula or unsure how to structure knowledge."
        ),
    )
    def get_memory_guide() -> str:
        return _memory_guide_text()

    from kapsula.infrastructure.logging_config import get_logger

    get_logger(__name__).info("Registered 36 MCP tools across 6 modules")
