"""Factory for MCP background search job runners.

Eliminates duplicated try/except/finally blocks from the tools module
by producing runner coroutines from a search function and metadata.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from doc_search.infrastructure.logging_config import get_logger
from doc_search.presentation.mcp.search_jobs import SearchJob, SearchJobManager

logger = get_logger(__name__)


def make_search_job_runner(
    search_fn: Callable[..., Awaitable[str]],
    manager: SearchJobManager,
    progress_label: str,
) -> Callable[[SearchJob], Awaitable[None]]:
    """Create a background job runner for a search function.

    Args:
        search_fn: Async callable that performs the search and returns text.
        manager: Job manager for progress tracking.
        progress_label: Human-readable label for progress messages.
    """

    async def _runner(job: SearchJob) -> None:
        manager.update(job, status="running", progress=f"{progress_label} running")
        try:
            result = await search_fn(**job.params)
            manager.update(
                job,
                status="completed",
                progress=f"{progress_label} completed",
                result=result,
            )
        except asyncio.CancelledError:
            manager.update(
                job, status="cancelled", progress=f"{progress_label} cancelled"
            )
            raise
        except Exception as exc:
            logger.error(
                "Background %s job failed: %s", progress_label, exc, exc_info=True
            )
            manager.update(
                job,
                status="failed",
                progress=f"{progress_label} failed",
                error=str(exc),
            )

    return _runner
