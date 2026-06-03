from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel
from kapsula.presentation.api.dto.citation import Citation
from kapsula.presentation.api.dto.search_plan import SearchPlan
from kapsula.presentation.api.dto.sub_answer import SubAnswer


class IntelligentSearchResponse(BaseModel):
    """Response model for intelligent search on document."""

    job_id: str
    query: str
    answer: str
    has_answer: bool
    relevant_results: List[int]
    total_evaluated: int
    context_mode: Optional[str] = None
    plan: Optional[SearchPlan] = None
    sub_answers: Optional[List[SubAnswer]] = None
    citations: Optional[List[Citation]] = (
        None  # All unique citations from search results
    )
