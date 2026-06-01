"""Presentation layer — MCP tools exposed to MCP clients.

The MCP server lives in the startup layer (composition root):
    from doc_search.startup.mcp import create_server, run

Run with: python -m doc_search.presentation.mcp
"""

from .server import create_server

__all__ = ["create_server"]
