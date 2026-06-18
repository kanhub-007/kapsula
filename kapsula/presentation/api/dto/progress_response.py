"""Upload progress response API DTO."""

from pydantic import BaseModel


class ProgressResponse(BaseModel):
    """Response model for progress tracking."""

    status: str
    progress: int
    stage: str
    message: str
    chunk_count: int | None = None
    duration: float | None = None
