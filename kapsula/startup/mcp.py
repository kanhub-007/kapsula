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
            "Document search engine designed as a memory system for AI agents. "
            "Knowledge is organized in a 3-level hierarchy: "
            "Account (tenant/brain) → Collection (knowledge domain) → Document (topic/fact-cluster). "
            "\n\n"
            "MEMORY MODEL — how to structure knowledge:\n"
            "• Stable, interconnected knowledge → one medium document (1-5 pages). "
            "  The Russian Doll chunker splits by H2 headings, preserving cross-section context for search.\n"
            "• Frequently changing facts → separate small document (1-3 paragraphs). "
            "  Isolate volatile information so updates touch minimal chunks.\n"
            "• Independent reference tables (prices, dosages, configs) → separate small document.\n"
            "• Use descriptive H2/H3 headings to define sub-document boundaries.\n"
            "\n"
            "UPDATING KNOWLEDGE — to modify facts:\n"
            "1. Use get_collection() to find the document by filename and get its job_id.\n"
            "2. Delete the old document with delete_document(job_id).\n"
            "3. Re-upload the updated file.\n"
            "The system is append-optimized: deleting + re-uploading is the intended update path. "
            "Aggregate indexes rebuild automatically after delete, so searches reflect current knowledge.\n"
            "\n"
            "SEARCH — three scopes available:\n"
            "• search_collection() — scoped to one knowledge domain, fastest and most precise.\n"
            "• search_documents() — across all collections in an account.\n"
            "• intelligent_search() — LLM plans sub-questions, searches, and synthesizes a grounded answer."
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
