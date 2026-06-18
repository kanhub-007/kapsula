"""MCP background search tools — async search job management."""

import asyncio

from fastmcp import FastMCP

from ._shared import _get_search_job_manager
from ._search_helpers import (
    run_search_documents_text,
    run_intelligent_collection_search,
)


def register_search_background_tools(mcp: FastMCP):
    """Register background/async search tools."""

    async def _execute_search_job(job) -> None:
        manager = _get_search_job_manager()
        manager.update(job, status="running", progress="Search running")
        try:
            result = await run_search_documents_text(**job.params)
            manager.update(job, status="completed", progress="Search completed", result=result)
        except asyncio.CancelledError:
            manager.update(job, status="cancelled", progress="Search cancelled")
            raise
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Background search job failed: %s", exc, exc_info=True)
            manager.update(job, status="failed", progress="Search failed", error=str(exc))

    async def _execute_intelligent_search_job(job) -> None:
        manager = _get_search_job_manager()
        manager.update(job, status="running", progress="Intelligent search running")
        try:
            result = await run_intelligent_collection_search(
                query=job.params["query"],
                top_k=job.params.get("top_k", 10),
                context_mode=job.params.get("context_mode", "none"),
                account_id=job.params.get("account_id"),
                enable_planning=job.params.get("enable_planning", True),
                node_type_filter=job.params.get("node_type_filter"),
            )
            manager.update(job, status="completed", progress="Intelligent search completed", result=result)
        except asyncio.CancelledError:
            manager.update(job, status="cancelled", progress="Intelligent search cancelled")
            raise
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Background intelligent search job failed: %s", exc, exc_info=True)
            manager.update(job, status="failed", progress="Intelligent search failed", error=str(exc))

    @mcp.tool(
        name="start_search_documents",
        description=(
            "Start a background hybrid search and return a search_job_id for polling. "
            "Use this for long-running searches where you want to poll progress asynchronously. "
            "After starting, use get_search_progress(job_id) to check status and "
            "get_search_results(job_id) when status='completed'. "
            "context_mode: 'none'/'narrow'/'deep'. node_type_filter: comma-separated like 'table,code'."
        ),
    )
    async def start_search_documents(
        query: str,
        top_k: int = 10,
        context_mode: str = "none",
        account_id: str | None = None,
        collection_id: str | None = None,
        routing_mode: str = "auto",
        node_type_filter: str | None = None,
    ) -> str:
        job = _get_search_job_manager().start(
            params={
                "query": query,
                "top_k": top_k,
                "context_mode": context_mode,
                "account_id": account_id,
                "collection_id": collection_id,
                "routing_mode": routing_mode,
                "node_type_filter": node_type_filter,
            },
            runner=_execute_search_job,
        )
        return (
            "Search job started.\n"
            f"  search_job_id: {job.job_id}\n"
            f"  status: {job.status}\n"
            "Use get_search_progress and get_search_results to poll it."
        )

    @mcp.tool(
        name="get_search_progress",
        description="Get status and progress for a background search job.",
    )
    def get_search_progress(search_job_id: str) -> str:
        job = _get_search_job_manager().get(search_job_id)
        if not job:
            return f"Search job not found: {search_job_id}"
        return (
            f"Search job: {job.job_id}\n"
            f"status: {job.status}\n"
            f"progress: {job.progress}\n"
            f"created_at: {job.created_at.isoformat()}\n"
            f"updated_at: {job.updated_at.isoformat()}"
            + (f"\nerror: {job.error}" if job.error else "")
        )

    @mcp.tool(
        name="get_search_results",
        description="Get results for a completed background search job.",
    )
    def get_search_results(search_job_id: str) -> str:
        job = _get_search_job_manager().get(search_job_id)
        if not job:
            return f"Search job not found: {search_job_id}"
        if job.status == "completed":
            return job.result or "No results found."
        if job.status == "failed":
            return f"Search job failed: {job.error or 'unknown error'}"
        if job.status == "cancelled":
            return "Search job was cancelled."
        return (
            f"Search job not complete yet. status={job.status}, progress={job.progress}"
        )

    @mcp.tool(
        name="cancel_search",
        description="Cancel a running background search job where practical.",
    )
    def cancel_search(search_job_id: str) -> str:
        job = _get_search_job_manager().get(search_job_id)
        if not job:
            return f"Search job not found: {search_job_id}"
        if job.status in {"completed", "failed", "cancelled"}:
            return f"Search job already {job.status}."
        _get_search_job_manager().cancel(search_job_id)
        return f"Cancellation requested for search_job_id: {search_job_id}"

    @mcp.tool(
        name="start_intelligent_search",
        description=(
            "Start a background intelligent (LLM-powered) search and return a search_job_id. "
            "Poll with get_intelligent_search_progress(job_id) and retrieve with "
            "get_intelligent_search_results(job_id) when status='completed'. "
            "This is the async version of intelligent_search — use for complex queries "
            "that may take time. context_mode: 'none'/'narrow'/'deep'."
        ),
    )
    async def start_intelligent_search(
        query: str,
        top_k: int = 10,
        context_mode: str = "none",
        account_id: str | None = None,
        enable_planning: bool = True,
        node_type_filter: str | None = None,
    ) -> str:
        job = _get_search_job_manager().start(
            params={
                "query": query,
                "top_k": top_k,
                "context_mode": context_mode,
                "account_id": account_id,
                "enable_planning": enable_planning,
                "node_type_filter": node_type_filter,
            },
            runner=_execute_intelligent_search_job,
        )
        return (
            "Intelligent search job started.\n"
            f"  search_job_id: {job.job_id}\n"
            f"  status: {job.status}\n"
            "Use get_intelligent_search_progress and "
            "get_intelligent_search_results to poll it."
        )

    @mcp.tool(
        name="get_intelligent_search_progress",
        description="Get status and progress for a background intelligent search job.",
    )
    def get_intelligent_search_progress(search_job_id: str) -> str:
        job = _get_search_job_manager().get(search_job_id)
        if not job:
            return f"Search job not found: {search_job_id}"
        return (
            f"Search job: {job.job_id}\n"
            f"status: {job.status}\n"
            f"progress: {job.progress}\n"
            f"created_at: {job.created_at.isoformat()}\n"
            f"updated_at: {job.updated_at.isoformat()}"
            + (f"\nerror: {job.error}" if job.error else "")
        )

    @mcp.tool(
        name="get_intelligent_search_results",
        description="Get results for a completed background intelligent search job.",
    )
    def get_intelligent_search_results(search_job_id: str) -> str:
        job = _get_search_job_manager().get(search_job_id)
        if not job:
            return f"Search job not found: {search_job_id}"
        if job.status == "completed":
            return job.result or "No results found."
        if job.status == "failed":
            return f"Search job failed: {job.error or 'unknown error'}"
        if job.status == "cancelled":
            return "Search job was cancelled."
        return (
            f"Search job not complete yet. status={job.status}, progress={job.progress}"
        )
