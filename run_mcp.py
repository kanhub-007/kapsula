"""Convenience entry point — run with: python run_mcp.py

Starts the MCP server. Defaults to stdio transport.
Set DOCSEARCH_TRANSPORT=http to run on port 8002.

All startup logic lives in doc_search/startup/mcp.py (composition root).
"""

from doc_search.startup.mcp import run

if __name__ == "__main__":
    run()
