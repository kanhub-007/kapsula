"""Maintenance job state — plain dataclass, no framework dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MaintenanceJob:
    """Tracks the lifecycle of a background collection maintenance run."""

    job_id: str
    collection_id: str
    collection_name: str = "?"
    status: str = "queued"          # queued | running | completed | failed
    stage: str = "queued"           # queued | summarizing | indexing | consolidating | completed
    progress: str = "Maintenance queued"
    summary_updates: int = 0
    summary_failures: int = 0
    collection_faiss: str | None = None
    collection_bm25: str | None = None
    account_faiss: str | None = None
    account_bm25: str | None = None
    cards_created: int = 0
    cards_updated: int = 0
    cards_enriched: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
