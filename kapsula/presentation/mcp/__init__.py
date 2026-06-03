"""Presentation layer — MCP tools exposed to MCP clients.

The MCP server lives in the startup layer (composition root):
    from kapsula.startup.mcp import create_server, run

Run with: python -m kapsula.presentation.mcp
"""

from .server import create_server

__all__ = ["create_server"]
