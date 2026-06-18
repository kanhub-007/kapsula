from __future__ import annotations

from pydantic import BaseModel


class DocumentInfo(BaseModel):
    """Document metadata information."""

    id: int
    job_id: str
    filename: str
    size: int
    created_at: str
    duration: float | None
    ip_address: str
