"""Compatibility re-exports for MCP search jobs."""

from doc_search.presentation.mcp.search_job import SearchJob as SearchJob
from doc_search.presentation.mcp.search_job_manager import (
    SearchJobManager as SearchJobManager,
)

__all__ = ["SearchJob", "SearchJobManager"]
