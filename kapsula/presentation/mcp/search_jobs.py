"""Compatibility re-exports for MCP search jobs."""

from kapsula.presentation.mcp.search_job import SearchJob as SearchJob
from kapsula.presentation.mcp.search_job_manager import (
    SearchJobManager as SearchJobManager,
)

__all__ = ["SearchJob", "SearchJobManager"]
