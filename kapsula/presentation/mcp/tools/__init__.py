"""MCP tools — kapsula operations exposed to MCP clients.

Each tool group lives in its own module and is registered via
a ``register_*_tools(mcp)`` function called by :func:`register_tools`.
"""

from fastmcp import FastMCP

from .accounts import register_account_tools
from .collections import register_collection_tools
from .documents import register_document_tools
from .search import register_search_tools
from .export import register_export_tools
from ._shared import _clear_cache


def register_tools(mcp: FastMCP):
    """Register all kapsula tools on the given MCP server instance."""
    register_account_tools(mcp)
    register_collection_tools(mcp)
    register_document_tools(mcp)
    register_search_tools(mcp)
    register_export_tools(mcp)

    from kapsula.infrastructure.logging_config import get_logger
    get_logger(__name__).info("Registered 19 MCP tools across 5 modules")
