"""MCP tools — kapsula operations exposed to MCP clients.

Each tool group lives in its own module and is registered via
a ``register_*_tools(mcp)`` function called by :func:`register_tools`.
"""

from fastmcp import FastMCP

from .accounts import register_account_tools
from .collections import register_collection_tools
from .documents import register_document_tools
from .search import register_search_tools
from .export import register_export_tools
from ._shared import _clear_cache


def _memory_guide_text() -> str:
    """Return the full usage guide for AI assistants."""
    return (
        "KAPSULA MEMORY SYSTEM — Usage Guide for AI Assistants\n"
        "=======================================================\n\n"
        "Kapsula is a structured knowledge memory system. You (the AI) can WRITE, READ, "
        "and UPDATE persistent knowledge across sessions.\n\n"
        "HIERARCHY\n"
        "  Account (top-level container, like a \"brain\" or tenant)\n"
        "    └─ Collection (a knowledge domain: \"Dog Training\", \"Project X\", \"API Docs\")\n"
        "        └─ Document (a markdown file of connected facts)\n"
        "            └─ Sub-documents (H1 sections) -> Chunks (H2/H3 sections)\n\n"
        "FIRST-TIME SETUP\n"
        "  1. list_accounts() — check if an account already exists\n"
        "  2. create_account(name=\"...\") — create if needed -> account_id\n"
        "  3. create_collection(name=\"...\", account_id=...) -> collection_id\n\n"
        "WRITING KNOWLEDGE (upload documents)\n"
        "  • Write a .md file to disk with well-structured H2/H3 headings.\n"
        "  • upload_document(file_path=\"/path/to/file.md\", collection_id=..., ingestion_mode=\"indexed\")\n"
        "  • Track progress: get_document_progress(job_id) or get_upload_job(job_id)\n"
        "  • Sizing: stable knowledge -> 1-5 page doc; volatile facts -> 1-3 paragraph doc;\n"
        "    reference tables -> separate small doc.\n"
        "  • ingestion_mode: \"fast\"=no indexes, \"indexed\"=FAISS+BM25 (default), \"full\"=indexes+summary\n\n"
        "READING / SEARCHING (three scopes)\n"
        "  • search_document(job_id, query, context_mode=\"deep\") — one specific document, most precise\n"
        "  • search_collection(collection_id, query, context_mode=\"deep\") — one knowledge domain\n"
        "  • search_documents(query, context_mode=\"deep\", account_id=...) — all collections in account\n"
        "  • intelligent_search(query, context_mode=\"deep\") — LLM plans sub-questions and synthesizes answer\n"
        "  • For LLM consumption always use context_mode=\"deep\" to get full H2 chapter context.\n"
        "  • node_type_filter=\"table,code\" restricts to specific content types.\n\n"
        "UPDATING KNOWLEDGE\n"
        "  1. get_collection(collection_id) — find the document's job_id by filename\n"
        "  2. delete_document(job_id) — soft-delete; indexes rebuild automatically\n"
        "  3. Re-upload the updated .md file\n"
        "  There is no in-place edit — delete + re-upload is the update path.\n\n"
        "MAINTENANCE (keep indexes and summaries current)\n"
        "  • After deleting or uploading documents, maintenance may be deferred.\n"
        "  • list_stale_maintenance() — check which collections need refreshing\n"
        "  • run_collection_maintenance(collection_id) — regenerate summary and rebuild indexes\n"
        "  • Maintenance workflow: upload/delete -> list_stale_maintenance -> run_collection_maintenance\n"
        "  • If search results seem incomplete, run maintenance on the affected collection.\n\n"
        "BACKGROUND SEARCH (for long queries)\n"
        "  • start_search_documents(...) -> search_job_id\n"
        "  • get_search_progress(search_job_id) -> poll status\n"
        "  • get_search_results(search_job_id) -> retrieve when status=\"completed\"\n"
        "  • cancel_search(search_job_id) -> abort if needed\n\n"
        "INSPECTING KNOWLEDGE\n"
        "  • get_collection(collection_id) — list all documents in a collection\n"
        "  • list_collections(account_id) — overview of all collections\n"
        "  • get_document_info(job_id) — chunk preview, structure skeleton\n"
        "  • download_document_structure(job_id) — full heading tree\n"
        "  • export_collection(collection_id) — full dump for external analysis\n\n"
        "BEST PRACTICES\n"
        "  • ALWAYS use context_mode=\"deep\" when retrieving for LLM consumption.\n"
        "  • For complex reasoning questions, use intelligent_search (not plain search).\n"
        "  • Scope searches as narrowly as possible: document > collection > global.\n"
        "  • After uploading, verify with get_document_progress() before searching.\n"
        "  • Use descriptive H2/H3 headings — they become sub-document boundaries.\n"
        "  • After deleting or uploading documents, call list_stale_maintenance() to check\n"
        "    for stale summaries/indexes, then run_collection_maintenance(collection_id)\n"
        "    to refresh them. This ensures search results stay current.\n"
        "  • Call this guide again anytime: get_memory_guide()\n"
    )


def register_tools(mcp: FastMCP):
    """Register all kapsula tools on the given MCP server instance."""
    register_account_tools(mcp)
    register_collection_tools(mcp)
    register_document_tools(mcp)
    register_search_tools(mcp)
    register_export_tools(mcp)

    @mcp.tool(
        name="get_memory_guide",
        description=(
            "Return a usage guide explaining how kapsula works as a memory system — "
            "the hierarchy, writing knowledge, searching, updating, and best practices. "
            "Call this FIRST if you're new to kapsula or unsure how to structure knowledge."
        ),
    )
    def get_memory_guide() -> str:
        return _memory_guide_text()

    from kapsula.infrastructure.logging_config import get_logger
    get_logger(__name__).info("Registered 20 MCP tools across 5 modules")
