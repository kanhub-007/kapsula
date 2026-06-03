"""Convenience entry point — run with: python run_mcp.py

Starts the MCP server. Defaults to stdio transport.
Set KAPSULA_TRANSPORT=http to run on port 8002.

All startup logic lives in kapsula/startup/mcp.py (composition root).
"""

from kapsula.startup.mcp import run

if __name__ == "__main__":
    run()
