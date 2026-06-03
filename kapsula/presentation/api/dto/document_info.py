from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class DocumentInfo(BaseModel):
    """Document metadata information."""

    id: int
    job_id: str
    filename: str
    size: int
    created_at: str
    duration: Optional[float]
    ip_address: str
