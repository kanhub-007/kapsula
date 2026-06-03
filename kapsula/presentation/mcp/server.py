"""MCP server — re-exported from the startup layer (composition root)."""

from kapsula.startup.mcp import create_server, get_transport_config

__all__ = ["create_server", "get_transport_config"]
