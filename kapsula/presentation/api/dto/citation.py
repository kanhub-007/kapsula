from __future__ import annotations

from pydantic import BaseModel


class Citation(BaseModel):
    """Citation information for tracing chunk origin."""

    library_card_id: int | None = None
    start_char: int
    end_char: int
    section_title: str
    section_level: str  # level_1, level_2, or level_3
