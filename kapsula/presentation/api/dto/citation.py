from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class Citation(BaseModel):
    """Citation information for tracing chunk origin."""

    library_card_id: Optional[int] = None
    start_char: int
    end_char: int
    section_title: str
    section_level: str  # level_1, level_2, or level_3
