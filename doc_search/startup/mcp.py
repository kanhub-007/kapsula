"""MCP server startup — composition root for the MCP transport.

Clean architecture: this module creates the FastMCP server, wires dependencies,
and provides the CLI runner. The presentation/mcp/ layer only declares tools.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

from fastmcp import FastMCP

from doc_search.startup import bootstrap

logger = logging.getLogger(__name__)


def create_server() -> FastMCP:
    """Build the FastMCP server with database bootstrapped and tools registered.

    Returns:
        Configured FastMCP server instance ready to run.
    """
    bootstrap()

    server = FastMCP(
        name="doc-search",
        instructions=(
            "Document search engine with hybrid dense+sparse retrieval, "
            "LLM-powered intelligent search, and semantic markdown chunking. "
            "Use the available tools to search documents, manage collections, "
            "and upload content."
        ),
    )

    from doc_search.presentation.mcp.tools import register_tools
    register_tools(server)

    config = get_transport_config()
    logger.info(f"MCP server configured: transport={config['transport']}")
    if config["transport"] == "http":
        logger.info(f"HTTP transport: {config['host']}:{config['port']}")

    return server


def get_transport_config() -> dict:
    """Read transport configuration from environment variables."""
    return {
        "transport": os.getenv("DOCSEARCH_TRANSPORT", "stdio").lower(),
        "host": os.getenv("DOCSEARCH_HOST", "127.0.0.1"),
        "port": int(os.getenv("DOCSEARCH_PORT", "8002")),
    }


def run():
    """Start the MCP server. Called by CLI entry points."""
    server = create_server()
    config = get_transport_config()

    if config["transport"] == "http":
        logger.info(f"Starting MCP server on http://{config['host']}:{config['port']}")
        server.run(
            transport="streamable-http",
            host=config["host"],
            port=config["port"],
        )
    else:
        logger.info("Starting MCP server on stdio")
        server.run(transport="stdio")
