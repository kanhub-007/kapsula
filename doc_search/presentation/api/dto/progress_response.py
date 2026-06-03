"""Upload progress response API DTO."""

from typing import Optional

from pydantic import BaseModel


class ProgressResponse(BaseModel):
    """Response model for progress tracking."""

    status: str
    progress: int
    stage: str
    message: str
    chunk_count: Optional[int] = None
    duration: Optional[float] = None
