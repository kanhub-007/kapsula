"""MCP server — re-exported from the startup layer (composition root)."""

from doc_search.startup.mcp import create_server, get_transport_config

__all__ = ["create_server", "get_transport_config"]
