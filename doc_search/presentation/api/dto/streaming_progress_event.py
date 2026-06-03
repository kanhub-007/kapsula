from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel


class StreamingProgressEvent(BaseModel):
    """Streaming event for intelligent search progress updates."""

    event_type: (
        str  # 'planning', 'subquestion_start', 'subquestion_complete', 'final_answer'
    )
    data: Dict[str, Any]  # Event-specific data
