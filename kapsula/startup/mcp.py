"""MCP server startup — composition root for the MCP transport.

Clean architecture: this module creates the FastMCP server, wires dependencies,
and provides the CLI runner. The presentation/mcp/ layer only declares tools.
"""

import logging
import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from kapsula.startup import bootstrap

load_dotenv()

logger = logging.getLogger(__name__)


def create_server() -> FastMCP:
    """Build the FastMCP server with database bootstrapped and tools registered.

    Returns:
        Configured FastMCP server instance ready to run.
    """
    bootstrap()

    server = FastMCP(
        name="kapsula",
        instructions=(
            "Kapsula is a structured knowledge memory system for AI agents. "
            "Call get_memory_guide() first for a complete usage guide. "
            "Knowledge is organized in a 3-level hierarchy: "
            "Account (tenant/brain) → Collection (knowledge domain) → Document (topic/fact-cluster). "
            "\n\n"
            "QUICK REFERENCE:\n"
            "• BROWSE FIRST: get_library_cards(collection_id) to see what knowledge exists, "
            "then formulate targeted queries — this is the core workflow.\n"
            "• Writing: upload_document() to add knowledge from .md files with H2/H3 headings. "
            "Headings become library cards and sub-document boundaries — without proper headings, "
            "navigation and context expansion cannot work.\n"
            "• Reading: search_collection() for domain-specific, intelligent_search() for AI-synthesized answers\n"
            "• Updating: get_collection() to find job_id → delete_document() → re-upload\n"
            "• Synthesizing: after uploading, run list_stale_maintenance() then run_collection_maintenance() "
            "to generate topic cards, rebuild indexes, and refresh summaries.\n"
            "• get_consolidation_status() shows synthesized topic/evolution/gap cards.\n"
            "• Always use context_mode='deep' when retrieving for LLM consumption.\n"
            "• Full details: call get_memory_guide()"
        ),
    )

    from kapsula.presentation.mcp.tools import register_tools

    register_tools(server)

    config = get_transport_config()
    logger.info(f"MCP server configured: transport={config['transport']}")
    if config["transport"] == "http":
        logger.info(f"HTTP transport: {config['host']}:{config['port']}")

    return server


def get_transport_config() -> dict:
    """Read transport configuration from environment variables."""
    return {
        "transport": os.getenv("KAPSULA_TRANSPORT", "stdio").lower(),
        "host": os.getenv("KAPSULA_HOST", "127.0.0.1"),
        "port": int(os.getenv("KAPSULA_PORT", "8002")),
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
