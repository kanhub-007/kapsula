"""MCP search tools — re-exports from split modules.

.. note:: This file is kept for backward compatibility.
"""

from fastmcp import FastMCP

from .search_documents import register_search_document_tools
from .search_intelligent import register_search_intelligent_tools
from .search_background import register_search_background_tools


def register_search_tools(mcp: FastMCP):
    """Register all search tools by delegating to sub-modules."""
    register_search_document_tools(mcp)
    register_search_intelligent_tools(mcp)
    register_search_background_tools(mcp)
