"""MCP background search job state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SearchJob:
    """Background search job state."""

    job_id: str
    status: str = "queued"
    progress: str = "Queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    result: str | None = None
    error: str | None = None
    task: asyncio.Task | None = None
    params: dict[str, Any] = field(default_factory=dict)
